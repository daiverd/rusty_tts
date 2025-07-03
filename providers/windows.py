"""
Windows TTS Provider
Simple proxy that forwards requests to Windows TTS service
"""

import requests
import base64
import subprocess
import tempfile
import os
import logging

# Set up logging
logger = logging.getLogger(__name__)
from . import BaseTTSEngine


class WindowsEngine(BaseTTSEngine):
    """Windows TTS Engine - forwards requests to Windows service"""
    
    def __init__(self, service_url=None):
        # Import config here to avoid circular imports
        from config import WINDOWS_TTS_URL, WINDOWS_TTS_TIMEOUT
        
        self.service_url = service_url or WINDOWS_TTS_URL
        self.timeout = WINDOWS_TTS_TIMEOUT
        self.name = 'windows'
        self.display_name = 'Windows TTS'
        super().__init__()
    
    def is_available(self):
        """Check if Windows service is available"""
        # Import config here to avoid circular imports
        from config import WINDOWS_TTS_ENABLED
        
        if not WINDOWS_TTS_ENABLED:
            return False
            
        try:
            response = requests.get(f"{self.service_url}/health", timeout=5)
            return response.status_code == 200 and response.json().get('status') == 'ok'
        except:
            return False
    
    def get_voices(self):
        """Get list of available Windows voices"""
        try:
            response = requests.get(f"{self.service_url}/providers", timeout=self.timeout)
            if response.status_code == 200:
                data = response.json()
                
                # Extract all voices from all Windows providers
                voices = []
                for provider_name, provider_data in data.items():
                    if provider_data.get('available'):
                        for voice in provider_data.get('voices', []):
                            # Use simple voice name
                            voices.append(voice['name'])
                
                return voices
            return []
        except Exception as e:
            logger.error(f"Error getting Windows voices: {e}")
            return []
    
    async def synthesize(self, text, voice, filename):
        """Synthesize text using Windows service and convert to MP3"""
        try:
            # Forward request to Windows service
            payload = {
                'text': text,
                'voice': voice
            }
            
            response = requests.post(
                f"{self.service_url}/synthesize",
                json=payload,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    audio_data = base64.b64decode(data['audio_data'])
                    audio_format = data.get('format')
                    
                    # Convert to MP3 using FFmpeg
                    if audio_format == 'raw_pcm':
                        return self._convert_raw_pcm_to_mp3(
                            audio_data, 
                            filename,
                            data.get('sample_rate', 22050),
                            data.get('bit_depth', 16),
                            data.get('channels', 1)
                        )
                    elif audio_format == 'wav':
                        return self._convert_wav_to_mp3(audio_data, filename)
                    else:
                        logger.warning(f"Unknown audio format from Windows service: {audio_format}")
                        return False
            else:
                logger.error(f"Windows service returned error: {response.status_code}")
                return False
            
        except Exception as e:
            logger.error(f"Windows TTS synthesis error: {e}")
            return False
    
    def _convert_raw_pcm_to_mp3(self, pcm_data, output_file, sample_rate, bit_depth, channels):
        """Convert raw PCM data to MP3 using FFmpeg"""
        try:
            cmd = [
                'ffmpeg', '-y',
                '-f', f's{bit_depth}le',  # signed little endian format
                '-ar', str(sample_rate),   # sample rate
                '-ac', str(channels),      # audio channels
                '-i', 'pipe:0',            # input from stdin
                '-c:a', 'libmp3lame',      # MP3 encoder
                '-b:a', '128k',            # bitrate
                '-q:a', '2',               # quality
                output_file
            ]
            
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            _stdout, stderr = process.communicate(input=pcm_data)
            
            if process.returncode == 0:
                return True
            else:
                logger.error(f"FFmpeg PCM conversion error: {stderr.decode()}")
                return False
                
        except Exception as e:
            logger.error(f"PCM to MP3 conversion error: {e}")
            return False
    
    def _convert_wav_to_mp3(self, wav_data, output_file):
        """Convert WAV data to MP3 using FFmpeg"""
        try:
            cmd = [
                'ffmpeg', '-y',
                '-i', 'pipe:0',       # input from stdin
                '-c:a', 'libmp3lame', # MP3 encoder
                '-b:a', '128k',       # bitrate
                '-q:a', '2',          # quality
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