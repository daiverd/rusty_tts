FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies and build tools in one layer, then clean up
RUN apt-get update && apt-get install -y \
    # Core utilities (keep these)
    curl \
    # Audio processing (keep)
    ffmpeg \
    # eSpeak-ng TTS engine (keep)
    espeak-ng \
    espeak-ng-data \
    # Festival TTS engine (keep)
    festival \
    festvox-kallpc16k \
    festvox-rablpc16k \
    festvox-don \
    # Flite TTS engine (keep)
    flite \
    # ALSA sound system (keep)
    alsa-utils \
    # Additional audio libraries (keep runtime)
    libsndfile1 \
    libportaudio2 \
    libportaudiocpp0 \
    # Build tools (will be removed)
    wget \
    git \
    build-essential \
    gcc \
    g++ \
    make \
    # Development headers (will be removed after build)
    libsndfile1-dev \
    python3-dev \
    unzip \
    # Install SAM TTS in the same layer
    && git clone https://github.com/s-macke/SAM.git /tmp/sam \
    && cd /tmp/sam \
    && make \
    && cp sam /usr/local/bin/ \
    && cd / \
    && rm -rf /tmp/sam \
    # Install DECtalk TTS from GitHub archive
    && wget -O /tmp/dectalk.zip https://github.com/dectalk/dectalk/archive/master.zip \
    && cd /tmp \
    && unzip dectalk.zip \
    && cd dectalk-master \
    && make -f Makefile.linux \
    && cp say /usr/local/bin/dectalk \
    && cd / \
    && rm -rf /tmp/dectalk* \
    # Clean up build dependencies and caches
    && apt-get remove -y \
        wget \
        git \
        build-essential \
        gcc \
        g++ \
        make \
        libsndfile1-dev \
        python3-dev \
        unzip \
    && apt-get autoremove -y \
    && apt-get autoclean \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /tmp/* \
    && rm -rf /var/tmp/*

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install Python dependencies and clean up pip cache
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir TTS \
    && pip cache purge \
    && rm -rf ~/.cache/pip \
    && rm -rf /tmp/* \
    && find /usr/local -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Copy application code
COPY . .

# Create audio files directory
RUN mkdir -p audio_files

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8887

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8887/health || exit 1

# Run the application
CMD ["python", "app.py"]