FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip cache purge && \
    rm -rf ~/.cache/pip && \
    rm -rf /tmp/*

# Bake in the voice models so there's no download at request time. To add a
# voice: add its name here (see https://github.com/rhasspy/piper/blob/master/VOICES.md)
# and to VOICES in service.py, then rebuild just this image.
RUN python -m piper.download_voices --download-dir /opt/piper/voices \
        en_US-lessac-medium en_US-amy-medium en_GB-alan-medium

COPY service.py .

ENV PYTHONUNBUFFERED=1
EXPOSE 8892

HEALTHCHECK --interval=15s --timeout=10s --start-period=60s --retries=5 \
    CMD curl -f http://localhost:8892/health || exit 1

CMD ["python", "service.py"]
