import subprocess
from pathlib import Path
from typing import List
from . import BaseTTSEngine, run_tts_pipeline_with_stdin

VOICES_DIR = Path("/opt/piper/voices")

VOICES = ["en_US-lessac-medium", "en_US-amy-medium", "en_GB-alan-medium"]


class PiperEngine(BaseTTSEngine):
    """Piper TTS Engine - fast local neural TTS (ONNX, CPU real-time)"""

    def get_voices(self) -> List[str]:
        return VOICES

    def is_available(self) -> bool:
        try:
            subprocess.run(["piper", "--help"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

        return all((VOICES_DIR / f"{voice}.onnx").exists() for voice in VOICES)

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        if voice not in VOICES:
            return False

        tts_cmd = [
            "piper",
            "-m", str(VOICES_DIR / f"{voice}.onnx"),
            "--data-dir", str(VOICES_DIR),
            "--output-file", "-",
        ]

        return run_tts_pipeline_with_stdin(tts_cmd, text, output_path, input_format="wav")
