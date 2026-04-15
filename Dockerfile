FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libsndfile1 wget && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download Piper pt_BR-faber-medium model at build time
RUN mkdir -p /app/models && \
    wget -q -O /app/models/pt_BR-faber-medium.onnx \
        "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx" && \
    wget -q -O /app/models/pt_BR-faber-medium.onnx.json \
        "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx.json"

COPY src/ src/

CMD ["python", "-m", "src.main"]
