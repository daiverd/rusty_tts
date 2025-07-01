# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a unified FastAPI-based text-to-speech service that supports multiple TTS engines and providers. The architecture consists of:

1. **Main Linux Service** (`app.py`) - FastAPI server with multiple TTS providers
2. **Windows Service** (`windows/app.py`) - Python 2.7 Flask service for Windows XP/SAPI integration via balcon.exe
3. **Provider System** - Modular TTS engine implementations in `providers/` directory
4. **TTSManager** - Central coordinator that manages all available TTS engines

The service supports both cloud-based APIs (Pollinations) and local TTS engines (eSpeak, Festival, Flite, DECtalk, SAM, Coqui TTS), with automatic provider detection and voice enumeration.

## Development Commands

### Running the Service

**Main Linux Service:**
```bash
python app.py
# Runs on http://localhost:8887
```

**Windows Service (Python 2.7):**
```bash
cd windows
python app.py
# Runs on http://localhost:5000
```

**Docker Development:**
```bash
# Build and run with docker-compose
docker-compose up --build

# Run in detached mode
docker-compose up -d --build

# Development mode (mount local code)
# Uncomment the volume mapping in docker-compose.yml first
docker-compose up --build
```

### Testing

**Integration Testing:**
```bash
python test_windows_integration.py
# Tests Windows service integration and provider functionality
```

**API Testing:**
```bash
# Test different providers
curl "http://localhost:8887/tts?text=Hello+World&provider=espeak&voice=en"
curl "http://localhost:8887/tts?text=Hello+World&provider=dectalk&voice=0"
curl "http://localhost:8887/tts?text=Hello+World&provider=sam"

# List available providers
curl "http://localhost:8887/providers"

# Health check
curl "http://localhost:8887/health"
```

### Dependencies

**Main Service:**
```bash
pip install -r requirements.txt
# Installs: elevenlabs, fastapi, google-cloud-texttospeech, requests, uvicorn
```

**Windows Service:**
```bash
cd windows
pip install -r requirements.txt
# Installs Python 2.7 compatible: Flask==0.12.5, requests
```

## Architecture Details

### Provider System
- Each TTS engine implements `BaseTTSEngine` interface in `providers/`
- Engines auto-detect availability via `is_available()` method
- Voice enumeration through `get_voices()` method
- Synthesis via async `synthesize()` method

### Key Components
- **TTSManager** (`tts_manager.py`): Central provider coordinator
- **Config** (`config.py`): Environment-based configuration with CORS, Windows service URL
- **Providers**: Modular engines supporting different TTS technologies
  - `pollinations.py`: Cloud-based API
  - `espeak.py`, `festival.py`, `flite.py`: Linux TTS engines
  - `dectalk.py`, `sam.py`: Compiled retro TTS engines
  - `coqui.py`: AI-based TTS models
  - `windows.py`: HTTP proxy to Windows service
  - `windows/providers/balcon.py`: SAPI 4/5 integration via balcon.exe

### Docker Architecture
- Multi-stage build compiling SAM and DECtalk from source with minimal build dependencies
- Optimized build stage (uses specific packages instead of build-essential meta-package)
- Runtime image with minimal size (build tools removed)
- Health checks and resource limits configured
- Audio file persistence via Docker volumes

### Windows Integration
- Separate Python 2.7 service for Windows XP compatibility
- Automatic SAPI version detection per voice
- Raw PCM output for SAPI 5, WAV fallback for SAPI 4
- HTTP API bridge between Linux and Windows services

## Configuration

### Environment Variables
- `CORS_ORIGINS`: Comma-separated allowed origins
- `AUDIO_DIR`: Directory for audio file storage (default: audio_files)
- `WINDOWS_TTS_URL`: Windows service URL (default: http://localhost:5000)
- `WINDOWS_TTS_ENABLED`: Enable Windows provider integration (default: false)
- `WINDOWS_TTS_TIMEOUT`: Request timeout for Windows service (default: 30)

### Key Files
- `config.py`: Main service configuration
- `windows/config.py`: Windows service configuration
- `docker-compose.yml`: Container orchestration
- `Dockerfile`: Multi-stage build with TTS engine compilation

## File Caching
Both services implement MD5-based filename generation for audio caching:
- Format: `{md5(text_provider_voice)}.mp3`
- Prevents regeneration of identical requests
- Files stored in `audio_files/` directory (configurable)