# =============================================================================
# BUILD STAGE - Compile custom TTS engines
# =============================================================================
FROM python:3.12-slim as builder

# Install minimal build dependencies
RUN apt-get update && apt-get install -y \
    wget \
    git \
    gcc \
    g++ \
    libc6-dev \
    make \
    cmake \
    pkg-config \
    autoconf \
    automake \
    libsndfile1-dev \
    && rm -rf /var/lib/apt/lists/*

# Build SAM TTS
RUN git clone --depth 1 https://github.com/vidarh/SAM.git /tmp/sam && \
    cd /tmp/sam && \
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

# Build retrochip: our standalone port of MAME's speech-chip cores
# (see native/retrochip/, BSD-3-Clause) plus the CLI that drives them
COPY native/retrochip /tmp/retrochip-src
RUN g++ -Wall -O2 -std=c++17 -o /usr/local/bin/retrochip \
        /tmp/retrochip-src/main.cpp /tmp/retrochip-src/tms5220.cpp \
        /tmp/retrochip-src/sp0256.cpp /tmp/retrochip-src/votrax.cpp && \
    rm -rf /tmp/retrochip-src

# Build TMS-Express: WAV -> TMS5220-native LPC-10 frame encoder
# (https://github.com/tornupnegatives/TMS-Express, GPL-3.0). Vendored here as
# a standalone compiled CLI, invoked only via subprocess by this project's
# Python code (never linked), so its GPL-3.0 does not propagate to rusty_tts.
RUN git clone --depth 1 https://github.com/tornupnegatives/TMS-Express.git /tmp/tms-express && \
    cd /tmp/tms-express && \
    cmake -B build -DCMAKE_BUILD_TYPE=Release \
        -DTMSEXPRESS_BUILD_TESTS=OFF -DTMSEXPRESS_BUILD_GUI=OFF && \
    cmake --build build --config Release -j"$(nproc)" && \
    cp build/tmsexpress /usr/local/bin/tms-express && \
    rm -rf /tmp/tms-express

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
COPY --from=builder /usr/local/bin/retrochip /usr/local/bin/
COPY --from=builder /usr/local/bin/tms-express /usr/local/bin/
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

# Pre-bake g2p_en's NLTK data (used by providers/votrax.py) so it's not
# fetched from the network at request time. NLTK data location naming
# changed between versions (averaged_perceptron_tagger vs the _eng
# variant); grab both so it resolves regardless of the installed nltk.
ENV NLTK_DATA=/usr/local/share/nltk_data
RUN python -c "\
import nltk; \
nltk.download('cmudict', download_dir='/usr/local/share/nltk_data'); \
nltk.download('averaged_perceptron_tagger', download_dir='/usr/local/share/nltk_data'); \
nltk.download('averaged_perceptron_tagger_eng', download_dir='/usr/local/share/nltk_data')"

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