"""
Coqui TTS Provider
Proxy that forwards requests to the coqui-tts sidecar service, which keeps
the neural TTS models warm in memory (see coqui/service.py).
"""

import base64
import logging
import subprocess
from pathlib import Path
from typing import List

import requests

from . import BaseTTSEngine

logger = logging.getLogger(__name__)


class CoquiTTSEngine(BaseTTSEngine):
    """Coqui TTS Engine - forwards requests to the coqui-tts sidecar"""

    def __init__(self, service_url=None):
        # Import config here to avoid circular imports
        from config import COQUI_TTS_URL, COQUI_TTS_TIMEOUT

        self.service_url = service_url or COQUI_TTS_URL
        self.timeout = COQUI_TTS_TIMEOUT
        super().__init__()

    def is_available(self) -> bool:
        from config import COQUI_TTS_ENABLED

        if not COQUI_TTS_ENABLED:
            return False

        try:
            response = requests.get(f"{self.service_url}/health", timeout=5)
            return response.status_code == 200 and response.json().get("status") == "ok"
        except Exception:
            return False

    def get_voices(self) -> List[str]:
        try:
            response = requests.get(f"{self.service_url}/voices", timeout=self.timeout)
            if response.status_code == 200:
                return response.json().get("voices", [])
            return []
        except Exception as e:
            logger.error(f"Error getting Coqui voices: {e}")
            return []

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            response = requests.post(
                f"{self.service_url}/synthesize",
                json={"text": text, "voice": voice},
                timeout=self.timeout,
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    wav_data = base64.b64decode(data["audio_data"])
                    return self._convert_wav_to_mp3(wav_data, str(output_path))

            logger.error(f"Coqui service returned error: {response.status_code} {response.text}")
            return False

        except Exception as e:
            logger.error(f"Coqui TTS synthesis error: {e}")
            return False

    def _convert_wav_to_mp3(self, wav_data: bytes, output_file: str) -> bool:
        """Convert WAV data to MP3 using FFmpeg"""
        try:
            cmd = [
                "ffmpeg", "-y",
                "-i", "pipe:0",
                "-c:a", "libmp3lame",
                "-b:a", "128k",
                "-q:a", "2",
                output_file
            ]

            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            _stdout, stderr = process.communicate(input=wav_data)

            if process.returncode == 0:
                return True
            else:
                logger.error(f"FFmpeg WAV conversion error: {stderr.decode()}")
                return False

        except Exception as e:
            logger.error(f"WAV to MP3 conversion error: {e}")
            return False
