import subprocess
from pathlib import Path
from typing import List
from . import BaseTTSEngine, run_tts_pipeline

class CoquiTTSEngine(BaseTTSEngine):
    """Coqui TTS Engine (assumes you have it installed)"""
    
    def get_voices(self) -> List[str]:
        # These would be your installed Coqui models
        return ["tts_models/en/ljspeech/tacotron2-DDC", 
                "tts_models/en/ljspeech/glow-tts"]
    
    def is_available(self) -> bool:
        try:
            subprocess.run(["tts", "--help"], 
                         capture_output=True, check=True)
            subprocess.run(["ffmpeg", "-version"], 
                         capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    
    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        # Coqui TTS can output to stdout with --pipe_out
        tts_cmd = [
            "tts",
            "--text", text,
            "--model_name", voice,
            "--pipe_out"  # Output WAV to stdout
        ]
        
        return run_tts_pipeline(tts_cmd, output_path, engine_name="coqui")