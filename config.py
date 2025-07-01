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
MAX_TEXT_LENGTH = 1000

# Windows TTS Service configuration
WINDOWS_TTS_URL = "http://localhost:5000"
WINDOWS_TTS_ENABLED = False
WINDOWS_TTS_TIMEOUT = 30