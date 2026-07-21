import shutil
from pathlib import Path
from typing import List
from . import BaseTTSEngine, run_tts_pipeline

class SAMEngine(BaseTTSEngine):
    """SAM (Software Automatic Mouth) - Classic 1982 C64 TTS"""

    def get_voices(self) -> List[str]:
        # SAM voice presets with speed/pitch/throat/mouth parameters
        return [
            "sam",           # Default SAM voice (72,64,128,128)
            "elf",           # Elf (72,64,110,160)
            "robot",  # Little Robot (92,60,190,190)
            "stuffy",    # Stuffy Guy (82,72,110,105)
            "old", # Little Old Lady (82,32,145,145)
            "alien" # Extra-Terrestrial (100,64,150,200)
        ]

    def is_available(self) -> bool:
        return shutil.which("sam") is not None

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        # Voice parameter mappings
        voice_params = {
            "sam": ["-speed", "72", "-pitch", "64", "-throat", "128", "-mouth", "128"],
            "elf": ["-speed", "72", "-pitch", "64", "-throat", "110", "-mouth", "160"],
            "robot": ["-speed", "92", "-pitch", "60", "-throat", "190", "-mouth", "190"],
            "stuffy": ["-speed", "82", "-pitch", "72", "-throat", "110", "-mouth", "105"],
            "old": ["-speed", "82", "-pitch", "32", "-throat", "145", "-mouth", "145"],
            "alien": ["-speed", "100", "-pitch", "64", "-throat", "150", "-mouth", "200"]
        }

        params = voice_params.get(voice, voice_params["sam"])

        # SAM command to output WAV to stdout
        sam_cmd = [
            "sam",
            *params,
            "-wav", "/dev/stdout",  # Output WAV to stdout
            text
        ]

        return run_tts_pipeline(sam_cmd, output_path)
