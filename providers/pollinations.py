import requests
import urllib.parse
from pathlib import Path
from typing import List
from . import BaseTTSEngine

class PollinationsEngine(BaseTTSEngine):
    """Pollinations API TTS Engine"""
    
    def get_voices(self) -> List[str]:
        return ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
    
    def is_available(self) -> bool:
        return True  # API-based, always available
    
    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        encoded_text = urllib.parse.quote(text)
        url = f"https://text.pollinations.ai/{encoded_text}"
        params = {
            "model": "openai-audio",
            "voice": voice
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            
            if 'audio/mpeg' in response.headers.get('Content-Type', ''):
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                return True
            return False
        except requests.exceptions.RequestException:
            return False