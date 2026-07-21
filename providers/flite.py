import subprocess
from pathlib import Path
from typing import List
from . import BaseTTSEngine, run_tts_pipeline

class FliteEngine(BaseTTSEngine):
    """Flite (Festival Lite) TTS Engine"""

    def get_voices(self) -> List[str]:
        # Common Flite voices - you can expand this based on what's installed
        return ["kal16", "kal", "awb", "rms", "slt"]

    def is_available(self) -> bool:
        try:
            subprocess.run(["flite", "-lv"],
                         capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        # Flite command to output WAV to stdout
        flite_cmd = [
            "flite",
            "-voice", voice,
            "-t", text,
            "-o", "/dev/stdout"  # Output to stdout
        ]

        return run_tts_pipeline(flite_cmd, output_path)
