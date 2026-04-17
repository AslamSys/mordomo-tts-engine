import asyncio
import base64
import json
import logging
import time

import nats

from src import config
from src.synthesizer import PiperSynthesizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class TTSService:
    def __init__(self):
        self.nc = None
        self.synthesizer = PiperSynthesizer()
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._stream_queues: dict[str, asyncio.Queue] = {}

    async def start(self):
        self.synthesizer.load()

        self.nc = await nats.connect(config.NATS_URL)
        logger.info("Connected to NATS at %s", config.NATS_URL)

        # Full-text generation (legacy/non-streaming path)
        await self.nc.subscribe("mordomo.tts.generate.*", cb=self._on_generate)
        # Streaming sentence-by-sentence from Brain
        await self.nc.subscribe("mordomo.tts.stream.*", cb=self._on_stream_sentence)
        await self.nc.subscribe("mordomo.tts.interrupt.*", cb=self._on_interrupt)

        asyncio.create_task(self._heartbeat_loop())
        logger.info("TTS Engine started (engine=%s, streaming=enabled)", config.DEFAULT_ENGINE)

    async def _on_generate(self, msg):
        """Handle full-text TTS request (non-streaming path)."""
        try:
            data = json.loads(msg.data)
        except Exception:
            return

        text = data.get("text", "").strip()
        if not text:
            return

        speaker_id = msg.subject.removeprefix("mordomo.tts.generate.").split(".")[-1]
        if speaker_id in self._active_tasks:
            self._active_tasks[speaker_id].cancel()

        task = asyncio.create_task(self._synthesize(speaker_id, text))
        self._active_tasks[speaker_id] = task

    async def _on_stream_sentence(self, msg):
        """Handle streamed sentence from Brain — synthesize immediately."""
        try:
            data = json.loads(msg.data)
        except Exception:
            return

        text = data.get("text", "").strip()
        is_final = data.get("is_final", False)
        speaker_id = msg.subject.removeprefix("mordomo.tts.stream.").split(".")[-1]

        if not text and not is_final:
            return

        # Create a streaming task per speaker if not already active
        if speaker_id not in self._stream_queues:
            queue: asyncio.Queue = asyncio.Queue()
            self._stream_queues[speaker_id] = queue
            # Cancel any existing non-streaming task for this speaker
            if speaker_id in self._active_tasks:
                self._active_tasks[speaker_id].cancel()
            task = asyncio.create_task(self._stream_worker(speaker_id, queue))
            self._active_tasks[speaker_id] = task

        await self._stream_queues[speaker_id].put((text, is_final))

    async def _stream_worker(self, speaker_id: str, queue: asyncio.Queue):
        """Worker that synthesizes sentences from a queue as they arrive."""
        try:
            await self.nc.publish(
                f"mordomo.tts.status.{speaker_id}",
                json.dumps({
                    "status": "started",
                    "speaker_id": speaker_id,
                    "engine": "piper",
                    "streaming": True,
                    "timestamp": time.time(),
                }).encode(),
            )

            chunk_index = 0
            loop = asyncio.get_event_loop()

            while True:
                text, is_final = await queue.get()

                if text:
                    # Synthesize this sentence and stream audio chunks immediately
                    chunks = await loop.run_in_executor(
                        None,
                        lambda t=text: list(self.synthesizer.synthesize_chunks(t)),
                    )
                    for chunk in chunks:
                        payload = {
                            "data": base64.b64encode(chunk).decode(),
                            "chunk_index": chunk_index,
                            "is_final": False,
                            "sample_rate": config.PIPER_SAMPLE_RATE,
                            "timestamp": time.time(),
                            "engine": "piper",
                        }
                        await self.nc.publish(
                            f"mordomo.tts.audio_chunk.{speaker_id}",
                            json.dumps(payload).encode(),
                        )
                        chunk_index += 1
                        await asyncio.sleep(0)

                if is_final:
                    # Send final empty chunk to signal end of stream
                    await self.nc.publish(
                        f"mordomo.tts.audio_chunk.{speaker_id}",
                        json.dumps({
                            "data": "",
                            "chunk_index": chunk_index,
                            "is_final": True,
                            "sample_rate": config.PIPER_SAMPLE_RATE,
                            "timestamp": time.time(),
                            "engine": "piper",
                        }).encode(),
                    )

                    await self.nc.publish(
                        f"mordomo.tts.status.{speaker_id}",
                        json.dumps({
                            "status": "completed",
                            "speaker_id": speaker_id,
                            "engine": "piper",
                            "chunks_sent": chunk_index,
                            "streaming": True,
                            "timestamp": time.time(),
                        }).encode(),
                    )
                    logger.info("Stream synthesis completed: speaker=%s chunks=%d", speaker_id, chunk_index)
                    break

        except asyncio.CancelledError:
            logger.info("Stream synthesis cancelled for speaker=%s", speaker_id)
        except Exception as e:
            logger.error("Stream synthesis error for speaker=%s: %s", speaker_id, e)
        finally:
            self._active_tasks.pop(speaker_id, None)
            self._stream_queues.pop(speaker_id, None)

    async def _on_interrupt(self, msg):
        speaker_id = msg.subject.removeprefix("mordomo.tts.interrupt.").split(".")[-1]
        if speaker_id in self._active_tasks:
            self._active_tasks[speaker_id].cancel()
            del self._active_tasks[speaker_id]
            self._stream_queues.pop(speaker_id, None)

            await self.nc.publish(
                f"mordomo.tts.status.{speaker_id}",
                json.dumps({
                    "status": "interrupted",
                    "speaker_id": speaker_id,
                    "timestamp": time.time(),
                }).encode(),
            )
            logger.info("Synthesis interrupted for speaker=%s", speaker_id)

    async def _synthesize(self, speaker_id: str, text: str):
        """Non-streaming full-text synthesis (legacy path)."""
        try:
            await self.nc.publish(
                f"mordomo.tts.status.{speaker_id}",
                json.dumps({
                    "status": "started",
                    "speaker_id": speaker_id,
                    "engine": "piper",
                    "timestamp": time.time(),
                }).encode(),
            )

            loop = asyncio.get_event_loop()
            chunks = await loop.run_in_executor(
                None,
                lambda: list(self.synthesizer.synthesize_chunks(text)),
            )

            chunks_sent = 0
            for i, chunk in enumerate(chunks):
                is_final = i == len(chunks) - 1
                payload = {
                    "data": base64.b64encode(chunk).decode(),
                    "chunk_index": i,
                    "is_final": is_final,
                    "sample_rate": config.PIPER_SAMPLE_RATE,
                    "timestamp": time.time(),
                    "engine": "piper",
                }
                await self.nc.publish(
                    f"mordomo.tts.audio_chunk.{speaker_id}",
                    json.dumps(payload).encode(),
                )
                chunks_sent += 1
                await asyncio.sleep(0)

            await self.nc.publish(
                f"mordomo.tts.status.{speaker_id}",
                json.dumps({
                    "status": "completed",
                    "speaker_id": speaker_id,
                    "engine": "piper",
                    "chunks_sent": chunks_sent,
                    "timestamp": time.time(),
                }).encode(),
            )
            logger.info(
                "Synthesis completed: speaker=%s chunks=%d text='%s'",
                speaker_id, chunks_sent, text[:60],
            )

        except asyncio.CancelledError:
            logger.info("Synthesis cancelled for speaker=%s", speaker_id)
        except Exception as e:
            logger.error("Synthesis error for speaker=%s: %s", speaker_id, e)
        finally:
            self._active_tasks.pop(speaker_id, None)

    async def _heartbeat_loop(self):
        while True:
            await asyncio.sleep(config.HEARTBEAT_INTERVAL)
            payload = {
                "service": "tts-engine",
                "engine": config.DEFAULT_ENGINE,
                "timestamp": time.time(),
            }
            await self.nc.publish("tts.engine.status", json.dumps(payload).encode())


async def main():
    service = TTSService()
    await service.start()
    stop = asyncio.Event()
    await stop.wait()


if __name__ == "__main__":
    asyncio.run(main())
