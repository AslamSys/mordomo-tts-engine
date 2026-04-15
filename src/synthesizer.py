import logging
import subprocess
import struct
from src import config

logger = logging.getLogger(__name__)

PIPER_BIN = "/usr/local/bin/piper/piper"


class PiperSynthesizer:
    def __init__(self):
        self._ready = False

    def load(self):
        result = subprocess.run(
            [PIPER_BIN, "--version"],
            capture_output=True, text=True,
        )
        logger.info("Piper binary ready: %s", result.stdout.strip() or "ok")
        self._ready = True

    def synthesize(self, text: str) -> bytes:
        proc = subprocess.run(
            [
                PIPER_BIN,
                "--model", config.PIPER_MODEL_PATH,
                "--config", config.PIPER_CONFIG_PATH,
                "--output_raw",
            ],
            input=text.encode("utf-8"),
            capture_output=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Piper failed: {proc.stderr.decode()}")
        return proc.stdout

    def synthesize_chunks(self, text: str, chunk_size: int = config.CHUNK_SIZE_SAMPLES):
        pcm = self.synthesize(text)
        chunk_bytes = chunk_size * 2  # 16-bit = 2 bytes per sample
        for i in range(0, len(pcm), chunk_bytes):
            yield pcm[i : i + chunk_bytes]
