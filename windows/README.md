# Windows TTS Service

A Python 2.7 compatible TTS service for Windows XP that provides HTTP API access to balcon.exe and Windows SAPI voices.

## Features

- **SAPI 4 & 5 Support**: Automatic detection and handling of both SAPI versions
- **Efficient Audio Pipeline**: Raw PCM output for SAPI 5, WAV fallback for SAPI 4
- **RESTful API**: Compatible endpoints with main Linux TTS service
- **Voice Detection**: Automatic SAPI version detection per voice
- **Caching**: File-based audio caching to prevent regeneration
- **Unicode Support**: Proper handling of international text in Python 2.7

## Requirements

- Windows XP or later
- Python 2.7
- balcon.exe (included in providers/balcon directory)
- Flask 0.12.5 (last Python 2.7 compatible version)

## Installation

1. Install Python 2.7 on Windows XP
2. Install requirements:
   ```cmd
   pip install -r requirements.txt
   ```
3. Ensure balcon.exe is in the same directory as app.py
4. Run the service:
   ```cmd
   python app.py
   ```

## API Endpoints

### GET /
API information and available providers

### GET /health
Service health check

### GET /tts
Generate TTS audio (GET method for simple requests)
- `text`: Text to synthesize
- `provider`: TTS provider (default: balcon)
- `voice`: Voice name (default: Microsoft Sam)

### POST /synthesize
Advanced TTS synthesis with parameters
```json
{
  "text": "Hello World",
  "provider": "balcon",
  "voice": "Microsoft David",
  "rate": 0,
  "pitch": 0,
  "volume": 100
}
```

### GET /providers
List all available providers and voices with capabilities

### GET /play/<filename>
Stream audio files

### GET /files
List generated audio files

## SAPI Version Handling

The service automatically detects SAPI version for each voice:

**SAPI 5 Voices**:
- Raw PCM output via STDOUT (efficient)
- Rate/Pitch: -10 to 10
- Volume: 0-100
- Multi-language support

**SAPI 4 Voices**:
- WAV file output (with temp files)
- Rate/Pitch: 0-100
- No volume control
- Single language only

## Configuration

Edit `config.py` to customize:
- Audio directory
- Maximum text length
- Default voice
- CORS origins
- Cache settings

## Integration with Main Service

This Windows service is designed to work with the main Linux TTS service via HTTP API calls. The Linux service can call this Windows service to access Windows-specific TTS voices.

## Deployment

For production deployment:
1. Run on Windows XP VM
2. Configure firewall for port 5000
3. Set up reverse proxy if needed
4. Monitor service health

## Troubleshooting

**Common Issues**:
- **balcon.exe not found**: Ensure balcon.exe is in the same directory
- **Unicode errors**: Check that text is properly encoded as UTF-8
- **Voice not working**: Use `/providers` endpoint to check voice availability
- **SAPI detection fails**: Service defaults to SAPI 4 for safety

**Debug Mode**:
Set `DEBUG = True` in config.py for detailed error messages.

## File Structure

```
windows/
├── app.py                 # Main Flask application
├── config.py              # Configuration settings
├── requirements.txt       # Python 2.7 dependencies
├── providers/
│   ├── __init__.py
│   └── balcon.py          # Balcon provider implementation
└── audio_files/           # Generated audio cache (created automatically)
```