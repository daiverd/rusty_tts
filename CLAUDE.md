# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A unified FastAPI-based text-to-speech service that supports multiple TTS engines and providers. The application provides a RESTful API for converting text to speech using various synthesis methods including cloud APIs and local TTS engines.

## Development Commands

### Installation and Setup
```bash
pip install -r requirements.txt
```

### Running the Application
```bash
python app.py
```
The server runs on `http://0.0.0.0:8887` by default.

### Testing the API
```bash
# Basic TTS generation
curl "http://localhost:8887/tts?text=Hello+World&provider=pollinations&voice=alloy"

# List available providers
curl "http://localhost:8887/providers"

# Health check
curl "http://localhost:8887/health"
```

## Architecture

### Core Components

**TTSManager**: Central orchestrator that manages all TTS engines and handles provider selection and audio synthesis.

**BaseTTSEngine**: Abstract base class that defines the interface for all TTS engines. All engines must implement:
- `synthesize()`: Convert text to audio and save to file
- `get_voices()`: Return list of available voices
- `is_available()`: Check if engine dependencies are installed

**Engine Types**:
- **Cloud-based**: PollinationsEngine (API-based, always available)
- **Local TTS**: EspeakEngine, FestivalEngine, FliteEngine, DECtalkEngine, SAMEngine, CoquiTTSEngine
- **Effect engines**: LPCEngine (FFmpeg-based audio processing)

### Audio Pipeline

1. Text input via `/tts` endpoint
2. Provider validation and voice selection
3. Filename generation using MD5 hash of text+provider+voice
4. Cache check in `audio_files/` directory
5. If not cached, engine synthesis with subprocess pipes to FFmpeg for MP3 conversion
6. Return audio URL for streaming via `/play/{filename}`

### Engine Architecture Pattern

Most local engines follow this pattern:
1. Generate audio using native TTS binary (espeak, festival, flite, etc.)
2. Pipe raw audio output to FFmpeg via subprocess
3. Convert to MP3 format for consistent output
4. Handle errors gracefully and return boolean success status

### File Organization

- `app.py`: Main FastAPI application with API endpoints
- `tts_manager.py`: TTSManager class that orchestrates all TTS engines
- `config.py`: Configuration settings (CORS origins, audio directory, text limits)
- `providers/`: Directory containing TTS engine implementations
  - `__init__.py`: Base classes (TTSProvider, BaseTTSEngine) and shared pipeline utilities
  - `pollinations.py`: PollinationsEngine (cloud API)
  - `espeak.py`: EspeakEngine (local TTS)
  - `festival.py`: FestivalEngine (local TTS)
  - `flite.py`: FliteEngine (local TTS)
  - `dectalk.py`: DECtalkEngine (local TTS)
  - `sam.py`: SAMEngine (local TTS)
  - `lpc.py`: LPCEngine (FFmpeg effects)
  - `coqui.py`: CoquiTTSEngine (AI model)
- `audio_files/`: Directory for cached generated audio files (created automatically)
- `requirements.txt`: Python dependencies

## Key Implementation Details

- Audio caching prevents regeneration of identical text+provider+voice combinations
- CORS configured for common development origins
- All engines output MP3 format via FFmpeg conversion with optimized quality profiles
- Provider auto-detection based on binary availability
- Streaming audio responses with proper HTTP headers for browser playback
- Shared pipeline utilities in `providers/__init__.py` for subprocess management
- Engine initialization handled in TTSManager with availability checking
- Adaptive MP3 encoding: FFmpeg analyzes input audio and chooses optimal compression settings automatically