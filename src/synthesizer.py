import io
import logging
import wave
import numpy as np
from piper import PiperVoice
from src import config

logger = logging.getLogger(__name__)


class PiperSynthesizer:
    def __init__(self):
        self.voice: PiperVoice | None = None

    def load(self):
        logger.info("Loading Piper model from %s", config.PIPER_MODEL_PATH)
        self.voice = PiperVoice.load(
            config.PIPER_MODEL_PATH,
            config_path=config.PIPER_CONFIG_PATH,
        )
        logger.info("Piper model loaded (sample_rate=%d)", config.PIPER_SAMPLE_RATE)

    def synthesize(self, text: str) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(config.PIPER_SAMPLE_RATE)
            self.voice.synthesize(text, wf)

        buf.seek(44)  # skip WAV header
        return buf.read()

    def synthesize_chunks(self, text: str, chunk_size: int = config.CHUNK_SIZE_SAMPLES):
        pcm = self.synthesize(text)
        chunk_bytes = chunk_size * 2  # 16-bit = 2 bytes per sample
        for i in range(0, len(pcm), chunk_bytes):
            yield pcm[i : i + chunk_bytes]
