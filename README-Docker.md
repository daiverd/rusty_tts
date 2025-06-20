# Docker Setup for Rusty TTS

## Quick Start

```bash
# Build and run with docker-compose
docker-compose up --build

# Or run in detached mode
docker-compose up -d --build
```

The application will be available at `http://localhost:8887`

## Docker Files Created

- `Dockerfile` - Multi-stage build with all TTS dependencies
- `docker-compose.yml` - Complete orchestration setup
- `.dockerignore` - Optimized build context

## TTS Engines Installed

The Docker image includes:

- **eSpeak-ng** - Lightweight, multi-language TTS
- **Festival** - University of Edinburgh TTS system
- **Flite** - CMU Flite (festival-lite) TTS engine
- **DECtalk** - The famous Stephen Hawking voice (compiled from source)
- **SAM** - Software Automatic Mouth (retro TTS)
- **FFmpeg** - Audio processing and conversion
- **Coqui TTS** - AI-based TTS models (via pip)

## Environment Variables

- `CORS_ORIGINS` - Comma-separated list of allowed CORS origins
- `AUDIO_DIR` - Directory for audio file storage (default: audio_files)

## Volume Persistence

Audio files are stored in a Docker volume `audio_files` to persist between container restarts.

## Resource Limits

- Memory: 2GB limit, 512MB reserved
- CPU: 1.0 limit, 0.5 reserved

## Health Check

The container includes a health check that verifies the `/health` endpoint every 30 seconds.

## Usage Examples

```bash
# Test the API with different providers
curl "http://localhost:8887/tts?text=Hello+World&provider=espeak&voice=en"
curl "http://localhost:8887/tts?text=Hello+World&provider=dectalk&voice=0"  # Stephen Hawking voice
curl "http://localhost:8887/tts?text=Hello+World&provider=sam"

# List available providers
curl "http://localhost:8887/providers"

# Health check
curl "http://localhost:8887/health"
```

## Development Mode

To mount local code for development, uncomment the volume mapping in docker-compose.yml:

```yaml
volumes:
  - .:/app  # This line
```

## Image Optimization

The Dockerfile is optimized for minimal size:
- Multi-layer RUN commands combined to reduce layers
- Build tools removed after compilation (gcc, make, git, etc.)
- APT and pip caches cleared
- Python bytecode cache cleaned
- Temporary files removed

Final image size is significantly smaller than unoptimized builds.

## Troubleshooting

- If build fails, ensure you have sufficient disk space for build process
- Some TTS engines may require additional system audio setup
- DECtalk compilation from source may take several minutes during build
- Build process downloads and compiles both SAM and DECtalk TTS from source, then removes build tools
- If DECtalk build fails, check the GitHub repository for latest compilation requirements