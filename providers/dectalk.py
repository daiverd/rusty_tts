import subprocess
from pathlib import Path
from typing import List
from . import BaseTTSEngine, run_tts_pipeline_raw

class DECtalkEngine(BaseTTSEngine):
    """DECtalk TTS Engine - The famous Stephen Hawking voice"""

    def get_voices(self) -> List[str]:
        # DECtalk speaker numbers (0-9)
        return [
            "0",  # Perfect Paul (default, Stephen Hawking's voice)
            "1",  # Beautiful Betty
            "2",  # Huge Harry
            "3",  # Frail Frank
            "4",  # Doctor Dennis
            "5",  # Kit the Kid
            "6",  # Uppity Ursula
            "7",  # Rough Rita
            "8",  # Whispering Wendy
            "9"   # Variable (user-defined)
        ]

    def is_available(self) -> bool:
        try:
            subprocess.run(["dectalk", "-a", '"hi"', "-fo", "stdout:raw"],
                         capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        # DECtalk 'dectalk' command to output raw PCM to stdout
        dectalk_cmd = [
            "dectalk",
            "-s", voice,                    # Speaker number (0-9)
            "-fo", "stdout:raw",            # Output raw PCM to stdout
            "-a", text                      # Text to speak
        ]

        # DECtalk outputs raw PCM at a fixed 11025Hz mono
        return run_tts_pipeline_raw(dectalk_cmd, output_path, sample_rate=11025, channels=1)
