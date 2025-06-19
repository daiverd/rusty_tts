# rusty_tts

A unified FastAPI-based text-to-speech service that supports multiple TTS engines and providers, allowing you to generate audio from text using various synthesis methods.

## Features

- **Multiple TTS Providers**: Support for cloud-based APIs and local TTS engines
- **Voice Selection**: Different voices available per provider
- **Audio Caching**: Generated audio files are cached to avoid regeneration
- **RESTful API**: Simple HTTP endpoints for easy integration
- **Streaming Audio**: Direct audio file streaming for web playback
- **Provider Auto-Detection**: Automatically detects which TTS engines are available

## Supported Providers

The API supports various TTS providers including:
- Cloud-based services (like Pollinations)
- Local TTS engines (eSpeak, Festival, Flite, DECtalk, SAM)
- AI models (Coqui TTS)
- Custom effect engines ((currently broken) LPC-style processing)

## Quick Start

1. Install dependencies:
   ```bash
   pip install fastapi requests uvicorn
   ```

2. Run the server:
   ```bash
   python app.py
   ```

3. Generate speech:
   ```
   GET /tts?text=Hello+World&provider=pollinations&voice=alloy
   ```

## API Endpoints

- `GET /` - API information and available providers
- `GET /tts` - Generate audio from text
- `GET /play/{filename}` - Stream audio files
- `GET /providers` - List all available providers and voices
- `GET /files` - List generated audio files
- `GET /health` - Health check
