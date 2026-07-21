# CORS configuration
CORS_ORIGINS = [
    "https://tts.example.com",
    "http://localhost:3000",
    "http://localhost:8080",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8080"
]

# Audio configuration
AUDIO_DIR = "audio_files"
# Cached MP3s older than this are swept on a periodic background pass (see
# app.py's cleanup task) - the cache has no size cap, only an age one.
AUDIO_CACHE_MAX_AGE_DAYS = 30
AUDIO_CACHE_CLEANUP_INTERVAL_SECONDS = 3600

# Windows TTS Service configuration
WINDOWS_TTS_URL = "http://windows:5000"
WINDOWS_TTS_ENABLED = True
WINDOWS_TTS_TIMEOUT = 30

# Coqui TTS sidecar configuration
COQUI_TTS_URL = "http://coqui-tts:8891"
COQUI_TTS_ENABLED = True
COQUI_TTS_TIMEOUT = 300

# Piper TTS sidecar configuration
PIPER_URL = "http://piper-tts:8892"
PIPER_ENABLED = True
PIPER_TIMEOUT = 30
