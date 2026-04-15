import os

NATS_URL = os.getenv("NATS_URL", "nats://nats:4222")

PIPER_BIN = os.getenv("PIPER_BIN", "/usr/local/bin/piper/piper")
PIPER_MODEL_PATH = os.getenv("PIPER_MODEL_PATH", "/app/models/pt_BR-faber-medium.onnx")
PIPER_CONFIG_PATH = os.getenv("PIPER_CONFIG_PATH", "/app/models/pt_BR-faber-medium.onnx.json")
PIPER_SAMPLE_RATE = 22050

# Azure TTS (cloud - fallback)
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY", "")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "eastus")
AZURE_VOICE = os.getenv("AZURE_VOICE", "pt-BR-DonatoNeural")
AZURE_SAMPLE_RATE = 16000

# Engine selection
DEFAULT_ENGINE = os.getenv("TTS_ENGINE", "piper")  # piper | azure
LONG_TEXT_THRESHOLD = int(os.getenv("LONG_TEXT_THRESHOLD", "200"))

# Audio chunking
CHUNK_SIZE_SAMPLES = int(os.getenv("CHUNK_SIZE_SAMPLES", "4096"))

# Heartbeat
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "10"))
