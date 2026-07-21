FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir "transformers<5" "coqui-tts[codec,languages]" && \
    pip cache purge && \
    rm -rf ~/.cache/pip && \
    rm -rf /tmp/*

COPY service.py .

ENV PYTHONUNBUFFERED=1
EXPOSE 8891

# Model download/load on first boot can take several minutes; the health
# check only reports "ok" once every model in service.py's VOICES list has
# finished loading (see /health).
HEALTHCHECK --interval=30s --timeout=10s --start-period=600s --retries=10 \
    CMD curl -f http://localhost:8891/health || exit 1

CMD ["python", "service.py"]
