# -*- coding: utf-8 -*-
"""
Windows TTS Service Configuration
Python 2.7 Compatible
"""

import os

# Server Configuration
HOST = '0.0.0.0'
PORT = 5000
DEBUG = False

# Audio Configuration
AUDIO_DIR = 'audio_files'
MAX_TEXT_LENGTH = 5000
DEFAULT_VOICE = 'Microsoft Sam'

# Balcon Configuration
BALCON_EXECUTABLE = 'balcon.exe'

# Audio Format Settings
DEFAULT_SAMPLE_RATE = 22050
DEFAULT_BIT_DEPTH = 16
DEFAULT_CHANNELS = 1

# CORS Origins (if needed)
CORS_ORIGINS = [
    'http://localhost:3000',
    'http://localhost:8080',
    'http://127.0.0.1:3000',
    'http://127.0.0.1:8080'
]

# Cache settings
ENABLE_CACHING = True
CACHE_MAX_AGE = 86400  # 24 hours

def ensure_directories():
    """Ensure required directories exist"""
    if not os.path.exists(AUDIO_DIR):
        os.makedirs(AUDIO_DIR)