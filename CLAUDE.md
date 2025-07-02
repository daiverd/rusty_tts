# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

rusty_tts is a unified FastAPI-based text-to-speech service that supports multiple TTS engines and providers. The service provides a REST API to generate audio from text using various synthesis methods including cloud-based APIs and local TTS engines.

## Architecture

### Core Components

- `app.py` - Main FastAPI application with REST endpoints
- `tts_manager.py` - Central manager that coordinates multiple TTS engines
- `providers/` - Directory containing individual TTS engine implementations
- `config.py` - Configuration settings for CORS, audio directory, and provider settings

### Provider System

The application uses a plugin-like architecture where each TTS provider inherits from `BaseTTSEngine`:
- Cloud providers: Pollinations
- Local engines: eSpeak, Festival, Flite, DECtalk, SAM, Coqui TTS
- Platform-specific: Windows TTS (connects to Windows XP Python 2.7 sub-API)
- Experimental: LPC-style processing

Each provider auto-detects availability during initialization and only enabled providers are exposed through the API.

### Windows XP Sub-API Architecture

The Windows provider connects to a separate Python 2.7-based service running on Windows XP:
- **Location**: `windows/` directory contains the complete sub-API
- **Technology**: Flask-based HTTP API compatible with Python 2.7
- **Purpose**: Provides access to Windows SAPI 4/5 voices via balcon.exe
- **Communication**: HTTP requests from main API to Windows service (default port 5000)
- **Audio Pipeline**: Returns base64-encoded audio data (RAW PCM for SAPI 5, WAV for SAPI 4)

### Audio Pipeline

All TTS engines output audio through a unified pipeline:
1. TTS engine generates audio (typically WAV)
2. FFmpeg converts to MP3 with adaptive settings
3. Files are cached in `audio_files/` directory with hash-based naming

## Common Development Commands

### Running the Application

**Local development:**
```bash
python app.py
```

**Docker:**
```bash
docker-compose up --build
```

**Install dependencies:**
```bash
pip install -r requirements.txt
```

**Windows XP Sub-API:**
```cmd
cd windows
pip install -r requirements.txt
python app.py
```

### Testing

**Run Windows integration test:**
```bash
python test_windows_integration.py
```

**Test API endpoints manually:**
```bash
# Health check
curl http://localhost:8887/health

# List providers
curl http://localhost:8887/providers

# Generate speech
curl "http://localhost:8887/tts?text=Hello+World&provider=pollinations&voice=alloy"
```

### Configuration

- Main config in `config.py`
- Docker environment variables in `docker-compose.yml`
- Windows TTS requires separate Windows XP service running on port 5000
- Windows sub-API config in `windows/config.py`
- Set `WINDOWS_TTS_ENABLED = True` to enable Windows provider integration

## Key API Endpoints

- `GET /` - API information and available providers
- `GET /tts` - Generate audio from text (returns JSON with audio URL)
- `GET /play/{filename}` - Stream MP3 audio files
- `GET /providers` - List all available providers and voices
- `GET /files` - List generated audio files
- `GET /health` - Health check

## Development Notes

### Adding New TTS Providers

1. Create new provider class in `providers/` inheriting from `BaseTTSEngine`
2. Implement required methods: `synthesize()`, `get_voices()`, `is_available()`
3. Add import to `providers/__init__.py`
4. Add to engine initialization in `tts_manager.py`

### Audio Processing

- All providers must output to the provided `output_path` as MP3
- Use `run_tts_pipeline()` or `run_tts_pipeline_with_stdin()` helper functions for consistent FFmpeg processing
- Audio files are automatically cached based on text+provider+voice hash

### Windows XP Sub-API Details

**SAPI Version Detection:**
- Automatically detects SAPI 4 vs SAPI 5 for each voice
- SAPI 5: Raw PCM output, advanced rate/pitch controls (-10 to 10)
- SAPI 4: WAV file output, basic rate/pitch controls (0-100)

**Integration:**
- Main API calls Windows service via HTTP at `WINDOWS_TTS_URL` (default: http://localhost:5000)
- Audio data returned as base64-encoded strings
- Supports voice detection, synthesis, health checks

**Deployment:**
- Designed for Windows XP VM deployment
- Uses Python 2.7 with Flask 0.12.5 (last Python 2.7 compatible version)
- Requires balcon.exe in same directory as windows/app.py

### Error Handling

- Providers should return `False` from `synthesize()` on failure
- API returns HTTP 500 with provider-specific error messages
- Missing providers/voices return HTTP 400 with available options
- Windows provider gracefully handles sub-API unavailability