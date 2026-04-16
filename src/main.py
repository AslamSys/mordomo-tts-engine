import asyncio
import base64
import enum
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

    async def start(self):
        self.synthesizer.load()

        self.nc = await nats.connect(config.NATS_URL)
        logger.info("Connected to NATS at %s", config.NATS_URL)

        await self.nc.subscribe("mordomo.tts.generate.*", cb=self._on_generate)
        await self.nc.subscribe("mordomo.tts.interrupt.*", cb=self._on_interrupt)

        asyncio.create_task(self._heartbeat_loop())
        logger.info("TTS Engine started (engine=%s)", config.DEFAULT_ENGINE)

    async def _on_generate(self, msg):
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

    async def _on_interrupt(self, msg):
        speaker_id = msg.subject.removeprefix("mordomo.tts.interrupt.").split(".")[-1]
        if speaker_id in self._active_tasks:
            self._active_tasks[speaker_id].cancel()
            del self._active_tasks[speaker_id]

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

                # Small yield to allow interrupt checks
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
            await self.nc.publish(
                f"tts.status.{speaker_id}",
                json.dumps({
                    "status": "error",
                    "speaker_id": speaker_id,
                    "error": str(e),
                    "timestamp": time.time(),
                }).encode(),
            )
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
