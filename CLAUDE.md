# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

rusty_tts is a unified FastAPI-based text-to-speech service that supports multiple TTS engines and providers. The service provides a REST API to generate audio from text using various synthesis methods including cloud-based APIs and local TTS engines.

## Architecture

### Request Flow

```
HTTP Request → app.py → TTSManager → Provider Engine → FFmpeg Pipeline → MP3 Cache
```

1. `app.py` receives request at `/tts?text=...&provider=...&voice=...`
2. `generate_filename()` creates MD5 hash from text+provider+voice for caching
3. `TTSManager.synthesize()` delegates to the appropriate engine
4. Engine generates audio (WAV/PCM) and pipes through FFmpeg to MP3
5. MP3 cached in `audio_files/` and URL returned to client

### Core Components

- `app.py` - FastAPI application (port 8887) with REST endpoints
- `tts_manager.py` - Coordinates engines, checks availability, routes synthesis requests
- `providers/__init__.py` - `BaseTTSEngine` abstract class and FFmpeg pipeline helpers
- `config.py` - CORS origins, audio directory, Windows TTS connection settings

### Provider System

Each provider inherits from `BaseTTSEngine` and implements:
- `async synthesize(text: str, voice: str, output_path: Path) -> bool`
- `get_voices() -> List[str]`
- `is_available() -> bool`

Available providers:
- **Cloud**: Pollinations (always available)
- **Local engines**: eSpeak, Festival, Flite, DECtalk, SAM, Coqui TTS
- **Platform-specific**: Windows TTS (connects to Windows XP Python 2.7 sub-API)

Engines auto-detect availability on startup; only available providers are exposed via the API.

### Audio Pipeline Helpers

Two pipeline functions in `providers/__init__.py` handle FFmpeg conversion:

```python
# For engines that output to stdout
run_tts_pipeline(tts_cmd: List[str], output_path: Path, input_format: str = "wav") -> bool

# For engines requiring stdin input (e.g., Festival with Scheme scripts)
run_tts_pipeline_with_stdin(tts_cmd: List[str], stdin_data: str, output_path: Path, input_format: str = "wav") -> bool
```

For engines with raw PCM output (like DECtalk), specify format parameters:
```python
ffmpeg -f s16le -ar 11025 -ac 1 -i pipe:0 ...
```

### Windows XP Sub-API

The `windows/` directory contains Python 2.7 Flask service code for Windows SAPI access. This code must be **manually deployed** into a Windows XP VM.

```
┌─────────────────────────┐         ┌─────────────────────────────────┐
│  rusty_tts container    │  HTTP   │  ../windows (dockur/windows VM) │
│  providers/windows.py   │ ──────► │  rusty_tts/windows/ deployed    │
│  (client)               │ :23451  │  inside as Flask service        │
└─────────────────────────┘         └─────────────────────────────────┘
                    └─────────── rusty network ───────────┘
```

**Deployment:**
- The Windows VM is run by a **separate project** at `../windows` using [dockur/windows](https://github.com/dockur/windows)
- Both projects share the external `rusty` Docker network
- The VM mounts `../windows/data` as drive Z: - copy `rusty_tts/windows/` contents there
- Inside the VM: install Python 2.7, run `pip install -r requirements.txt`, then `python app.py`

**Technical details:**
- Uses Flask 0.12.5 (last Python 2.7 compatible version)
- Uses balcon.exe to interface with SAPI 4/5 voices
- Returns base64-encoded audio (RAW PCM for SAPI 5, WAV for SAPI 4)
- Main API connects via HTTP at `WINDOWS_TTS_URL` (default: http://windows:23451 in Docker)

## Common Development Commands

```bash
# Local development
pip install -r requirements.txt
python app.py

# Docker
docker-compose up --build

# Test endpoints
curl http://localhost:8887/health
curl http://localhost:8887/providers
curl "http://localhost:8887/tts?text=Hello+World&provider=pollinations&voice=alloy"

# Windows integration test
python test_windows_integration.py

# Windows sub-API (on Windows XP)
cd windows && pip install -r requirements.txt && python app.py
```

## Key API Endpoints

- `GET /` - API information and available providers
- `GET /tts` - Generate audio (params: `text`, `provider`, `voice`)
- `GET /play/{filename}` - Stream MP3 files
- `GET /providers` - List all available providers and voices
- `GET /files` - List generated audio files
- `GET /health` - Health check with provider status

## Adding New TTS Providers

1. Create `providers/yourengine.py` inheriting from `BaseTTSEngine`
2. Implement `synthesize()`, `get_voices()`, `is_available()`
3. Use `run_tts_pipeline()` or `run_tts_pipeline_with_stdin()` for FFmpeg conversion
4. Add import to `providers/__init__.py` and `__all__` list
5. Add engine instance to `tts_manager.py` `_initialize_engines()` dict

## Configuration

- `config.py` - Main settings (CORS_ORIGINS, AUDIO_DIR, WINDOWS_TTS_*)
- `docker-compose.yml` - Container config, port mapping (127.0.0.1:8887:8887)
- `windows/config.py` - Windows sub-API settings

Set `WINDOWS_TTS_ENABLED = True` in config.py to enable Windows provider integration.
