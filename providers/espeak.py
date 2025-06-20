import subprocess
from pathlib import Path
from typing import List
from . import BaseTTSEngine, run_tts_pipeline

class EspeakEngine(BaseTTSEngine):
    """eSpeak-ng TTS Engine"""
    
    def get_voices(self) -> List[str]:
        # These are common eSpeak voices, you can expand this
        return ["en", "en-us", "en-gb", "es", "fr", "de", "it"]
    
    def is_available(self) -> bool:
        try:
            subprocess.run(["espeak-ng", "--version"], 
                         capture_output=True, check=True)
            subprocess.run(["ffmpeg", "-version"], 
                         capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    
    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        espeak_cmd = [
            "espeak-ng", 
            "-v", voice,
            "-s", "150",  # Speed
            "--stdout",   # Output to stdout instead of file
            text
        ]
        
        return run_tts_pipeline(espeak_cmd, output_path, engine_name="espeak")