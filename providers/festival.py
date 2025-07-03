import subprocess
from pathlib import Path
from typing import List
from . import BaseTTSEngine, run_tts_pipeline_with_stdin

class FestivalEngine(BaseTTSEngine):
    """Festival TTS Engine"""
    
    def get_voices(self) -> List[str]:
        return ["kal_diphone", "rab_diphone", "don_diphone", "rms_diphone"]
    
    def is_available(self) -> bool:
        try:
            subprocess.run(["festival", "--version"], 
                         capture_output=True, check=True)
            subprocess.run(["ffmpeg", "-version"], 
                         capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    
    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        # Create Festival script that outputs to stdout
        festival_script = f'''
(voice_{voice})
(utt.save.wave 
  (utt.synth (Utterance Text "{text}"))
  "/dev/stdout" 'wav)
'''
        
        festival_cmd = ["festival"]
        
        return run_tts_pipeline_with_stdin(festival_cmd, festival_script, output_path)