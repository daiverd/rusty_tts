# =============================================================================
# BUILD STAGE - Compile custom TTS engines
# =============================================================================
FROM python:3.12-slim as builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    wget \
    git \
    build-essential \
    autoconf \
    automake \
    gcc \
    g++ \
    make \
    libsndfile1-dev \
    python3-dev \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Build SAM TTS
RUN git clone --depth 1 https://github.com/vidarh/SAM.git /tmp/sam && \
    cd /tmp/sam && \
    # Comment out SDL lines and uncomment non-SDL lines in Makefile
    sed -i 's/^CFLAGS.*USESDL.*/#&/' Makefile && \
    sed -i 's/^LFLAGS.*sdl-config.*/#&/' Makefile && \
    sed -i 's/^#CFLAGS.*Wall.*O2$/CFLAGS = -Wall -O2/' Makefile && \
    sed -i 's/^#LFLAGS =$/LFLAGS =/' Makefile && \
    make && \
    cp sam /usr/local/bin/sam && \
    rm -rf /tmp/sam

# Build DECtalk TTS
RUN git clone --depth 1 https://github.com/dectalk/dectalk.git /tmp/dectalk && \
    cd /tmp/dectalk/src && \
    ./autogen.sh && \
    ./configure && \
    make -j && \
    make install && \
    rm -rf /tmp/dectalk

# =============================================================================
# RUNTIME STAGE - Final application image
# =============================================================================
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install runtime system dependencies
RUN apt-get update && apt-get install -y \
    # Core utilities
    curl \
    # Audio processing
    ffmpeg \
    # eSpeak-ng TTS engine
    espeak-ng \
    espeak-ng-data \
    # Festival TTS engine (removing unavailable packages)
    festival \
    festvox-kallpc16k \
    # Note: festvox-rablpc16k and festvox-don are not available in Debian repos
    # Flite TTS engine
    flite \
    # ALSA sound system
    alsa-utils \
    # Audio libraries (runtime only)
    libsndfile1 \
    libportaudio2 \
    libportaudiocpp0 && \
    rm -rf /var/lib/apt/lists/*

# Copy compiled TTS engines from builder stage
COPY --from=builder /usr/local/bin/sam /usr/local/bin/
COPY --from=builder /opt/dectalk /opt/dectalk
RUN ln -s /opt/dectalk/say /usr/bin/dectalk && \
    echo "/opt/dectalk/lib" > /etc/ld.so.conf.d/dectalk.conf && ldconfig

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir TTS && \
    pip cache purge && \
    rm -rf ~/.cache/pip && \
    rm -rf /tmp/* && \
    find /usr/local -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

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