# syntax=docker/dockerfile:1
# ^ needed for the RUN --mount=type=cache below (mame-builder stage)

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
    libunicorn-dev \
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
# (see native/retrochip/, BSD-3-Clause) plus the CLI that drives them.
# Also build the standalone DoubleTalk PC emulator (vendored MAME 80C188EB
# core + board wrapper), sourced from the sibling doubletalk_pc repo via
# the doubletalk_src named build context (see docker-compose.yml) since
# it's used by providers/doubletalk.py.
COPY native/retrochip /tmp/retrochip-src
COPY --from=doubletalk_src doubletalk /tmp/retrochip-src/doubletalk
RUN rm -rf /tmp/retrochip-src/doubletalk/build && \
    g++ -Wall -O2 -std=c++17 -o /usr/local/bin/retrochip \
        /tmp/retrochip-src/main.cpp /tmp/retrochip-src/tms5220.cpp \
        /tmp/retrochip-src/sp0256.cpp /tmp/retrochip-src/votrax.cpp \
        /tmp/retrochip-src/tms5110.cpp /tmp/retrochip-src/s14001a.cpp && \
    make -C /tmp/retrochip-src/doubletalk -j"$(nproc)" build/dtalk_cli && \
    cp /tmp/retrochip-src/doubletalk/build/dtalk_cli /usr/local/bin/dtalk_cli && \
    rm -rf /tmp/retrochip-src

# Build libbst_shim: Unicorn-emulated Win32 shim for the BestSpeech/Keynote
# Gold engine (native/keynote/, vendored from cullen-gallagher/
# BestSpeechForMac - see that file's header comment). Runs the proprietary
# b32_tts.dll (mounted at runtime from roms/keynote/, not baked into this
# image - see roms/keynote/PROVENANCE.md) directly, with no Windows/Wine
# dependency - see providers/keynote.py.
COPY native/keynote /tmp/keynote-src
RUN gcc -O2 -fPIC -shared -Wall -o /usr/local/lib/libbst_shim.so \
        /tmp/keynote-src/bst_shim.c -lunicorn && \
    gcc -O2 -fPIC -shared -Wall -o /usr/local/lib/libbst_lang_shim.so \
        /tmp/keynote-src/bst_lang_shim.c -lunicorn && \
    rm -rf /tmp/keynote-src

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
# MAME BUILD STAGE - Scoped build covering the remaining real-hardware
# automation providers (Textalker/Echo II Plus, Votrax Type 'N Talk, Votrax
# Personal Speech System). DoubleTalk PC no longer builds through MAME - it
# uses the standalone emulator from the builder stage (sourced from the
# sibling doubletalk_pc repo, built above). Separate stage so unrelated
# app changes don't invalidate this ~15-20min build's Docker layer cache.
# =============================================================================
FROM debian:trixie-slim AS mame-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    build-essential \
    python3 \
    libsdl2-dev \
    libsdl2-ttf-dev \
    pkg-config \
    libfontconfig1-dev \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/mamedev/mame /mame
WORKDIR /mame

# Scoped build: only the drivers these providers need (each pulls in its
# own dependencies - a2bus/echoplus/tms5220, votrax/6802/6850, votrax/z80/
# i8251/i8255/ay8910 - automatically) - no Qt debugger, no dev tools.
# (DoubleTalk PC is NOT in this build: rusty_tts uses the standalone
# emulator sourced from the sibling doubletalk_pc repo; the MAME
# reference driver lives in the companion mame-doubletalk repo.)
#
# --mount=type=cache,target=/mame/build persists MAME's object-file/
# generated-source directory across separate `docker build` invocations,
# independent of Docker's normal layer-cache invalidation. Without it,
# any change that invalidates an earlier layer forces a full ~15-20min
# rebuild of the entire scoped driver set from nothing. With the mount,
# make's own mtime-based dependency tracking sees everything else as
# already-built (same content+mtimes as last time, since git clone's layer
# is still cache-hit and unchanged) and only recompiles+relinks what
# actually differs - seconds, not minutes, for a DoubleTalk-only edit. The
# final linked binary (/mame/mame) lands outside build/, so it's unaffected
# by the mount not persisting into the image layer.
RUN --mount=type=cache,target=/mame/build \
    make SOURCES=src/mame/apple/apple2e.cpp,src/mame/votrax/votrtnt.cpp,src/mame/votrax/votrpss.cpp \
    USE_QTDEBUG=0 REGENIE=1 NOWERROR=1 -j"$(nproc)"

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
    libportaudiocpp0 \
    # Runtime libs for the vendored MAME binary (Textalker automation).
    # libgl1 is a real, direct dependency of MAME's SDL2 build (it dlopens
    # libGL even with -video none) - it used to come along for free as a
    # transitive dependency of ffmpeg before ffmpeg was removed in favor of
    # in-process MP3 encoding (see providers/mp3_encoder.py), so it has to
    # be listed explicitly now.
    libsdl2-2.0-0 \
    libsdl2-ttf-2.0-0 \
    libfontconfig1 \
    libasound2 \
    libgl1 \
    # JRE for AppleCommander (writes the per-request HELLO program onto
    # the Textalker disk image - Textalker automation)
    default-jre-headless \
    # Runtime lib for libbst_shim.so (BestSpeech/Keynote Gold - providers/keynote.py)
    libunicorn2t64 && \
    rm -rf /var/lib/apt/lists/*

# AppleCommander (https://github.com/AppleCommander/AppleCommander,
# GPL-2.0): reads/writes DOS 3.3/ProDOS disk images, including tokenizing
# plain-text Applesoft BASIC source directly onto a disk. Vendored as a
# standalone jar, invoked only via subprocess (never linked), so its
# GPL-2.0 doesn't propagate to rusty_tts.
RUN mkdir -p /opt/applecommander && \
    curl -fsSL "https://github.com/AppleCommander/AppleCommander/releases/download/13.2/AppleCommander-ac-13.2.jar" \
        -o /opt/applecommander/ac.jar && \
    echo "354dd16c355982c80e92fce117cf44c16b87e50a5dcc2030997f1e02564de7b9  /opt/applecommander/ac.jar" | sha256sum -c -

# Copy compiled TTS engines from builder stage
COPY --from=builder /usr/local/bin/sam /usr/local/bin/
COPY --from=builder /usr/local/bin/retrochip /usr/local/bin/
COPY --from=builder /usr/local/bin/dtalk_cli /usr/local/bin/
COPY --from=builder /usr/local/bin/tms-express /usr/local/bin/
COPY --from=builder /opt/dectalk /opt/dectalk
COPY --from=builder /usr/local/lib/libbst_shim.so /usr/local/lib/
COPY --from=builder /usr/local/lib/libbst_lang_shim.so /usr/local/lib/
RUN ln -s /opt/dectalk/say /usr/bin/dectalk && \
    echo "/opt/dectalk/lib" > /etc/ld.so.conf.d/dectalk.conf && ldconfig

# Copy the vendored MAME binary (Apple IIe/Echo II Plus/Textalker
# automation - providers/textalker.py). Proprietary ROMs/disk image are
# NOT baked in here; they're mounted read-only at runtime from a
# gitignored mame_roms/ directory (see scripts/fetch_roms.sh).
COPY --from=mame-builder /mame/mame /opt/mame/mame

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip cache purge && \
    rm -rf ~/.cache/pip && \
    rm -rf /tmp/* && \
    (find /usr/local -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true)

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