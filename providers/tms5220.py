import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List

from . import BaseTTSEngine, run_tts_pipeline_stdin_raw

# TMS-Express (https://github.com/tornupnegatives/TMS-Express, GPL-3.0)
# analyzes audio at a fixed 8kHz to produce TMS5220-native LPC-10 frames;
# our ported chip core (native/retrochip) generates samples at the same
# implied rate.
_SAMPLE_RATE = 8000


class Tms5220Engine(BaseTTSEngine):
    """TMS5220 speech-chip emulator, driven by real LPC-10 frames encoded
    from another engine's voice via TMS-Express, then decoded by a
    standalone port of MAME's TMS5220 core (native/retrochip)."""

    def get_voices(self) -> List[str]:
        # Which existing engine's audio is fed through the TMS5220 chip.
        return ["espeak", "dectalk-0", "dectalk-1", "dectalk-2"]

    def is_available(self) -> bool:
        try:
            subprocess.run(["retrochip", "--chip", "tms5220"],
                            input=b"", capture_output=True)
            subprocess.run(["tms-express", "--help"],
                            capture_output=True, check=True)
            subprocess.run(["ffmpeg", "-version"],
                            capture_output=True, check=True)
            return shutil.which("espeak-ng") is not None
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def _synthesize_source_wav(self, text: str, voice: str, wav_path: Path) -> bool:
        """Produce a WAV file at wav_path using the engine named by `voice`."""
        if voice == "espeak":
            espeak_cmd = ["espeak-ng", "-v", "en", "-s", "150", "--stdout", text]
            with open(wav_path, "wb") as f:
                result = subprocess.run(espeak_cmd, stdout=f, stderr=subprocess.PIPE)
            return result.returncode == 0 and wav_path.exists()

        if voice.startswith("dectalk-"):
            speaker = voice.split("-", 1)[1]
            dectalk_cmd = ["dectalk", "-s", speaker, "-fo", "stdout:raw", "-a", text]
            ffmpeg_cmd = [
                "ffmpeg",
                "-f", "s16le", "-ar", "11025", "-ac", "1",
                "-i", "pipe:0",
                str(wav_path), "-y"
            ]
            dectalk_process = subprocess.Popen(dectalk_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            ffmpeg_process = subprocess.Popen(ffmpeg_cmd, stdin=dectalk_process.stdout,
                                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            dectalk_process.stdout.close()
            ffmpeg_process.communicate()
            dectalk_process.wait()
            return ffmpeg_process.returncode == 0 and wav_path.exists()

        return False

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp = Path(tmpdir)
                source_wav = tmp / "source.wav"
                frames_hex = tmp / "frames.lpc"

                if not self._synthesize_source_wav(text, voice, source_wav):
                    return False

                tms_express_cmd = [
                    "tms-express", "encode",
                    "-i", str(source_wav),
                    "-o", str(frames_hex),
                    "-f", "0",  # ascii hex, comma-delimited, no 0x prefix
                    # Push gain targets above TMS-Express's own defaults
                    # (37.5/30.0) - some source voices' gain analysis
                    # otherwise lands noticeably quieter than others.
                    "-v", "47.5", "-u", "40", "-g", "3",
                ]
                result = subprocess.run(tms_express_cmd, capture_output=True)
                if result.returncode != 0 or not frames_hex.exists():
                    return False

                hex_text = frames_hex.read_text().strip()
                if not hex_text:
                    return False
                frame_bytes = bytes(int(b, 16) for b in hex_text.split(","))

                retrochip_cmd = ["retrochip", "--chip", "tms5220"]
                return run_tts_pipeline_stdin_raw(
                    retrochip_cmd, frame_bytes, output_path,
                    sample_rate=_SAMPLE_RATE, channels=1
                )
        except Exception:
            return False
