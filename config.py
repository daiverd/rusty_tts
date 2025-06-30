import os

# CORS configuration
CORS_ORIGINS = os.getenv("CORS_ORIGINS", 
    "https://tts.example.com,http://localhost:3000,http://localhost:8080,http://127.0.0.1:3000,http://127.0.0.1:8080"
).split(",")

# Audio configuration
AUDIO_DIR = "audio_files"
MAX_TEXT_LENGTH = 1000

# Windows TTS Service configuration
WINDOWS_TTS_URL = os.getenv("WINDOWS_TTS_URL", "http://localhost:5000")
WINDOWS_TTS_ENABLED = os.getenv("WINDOWS_TTS_ENABLED", "false").lower() == "true"
WINDOWS_TTS_TIMEOUT = int(os.getenv("WINDOWS_TTS_TIMEOUT", "30"))