import os
import subprocess
import tempfile
from pathlib import Path
from typing import List

from . import BaseTTSEngine
from . import _mame_audio as mame_audio

_ROM_ROOT = mame_audio.ROM_ROOT
_LUA_SCRIPT = Path(__file__).resolve().parent.parent / "native" / "mame-votrax" / "capture.lua"

_REQUIRED_ROMS = [
    "votrtnt/cn49752n.bin",
    "votrtnt/sc01a.bin",
]


class VotraxTypeNTalkEngine(BaseTTSEngine):
    """Authentic Votrax Type 'N Talk (1980) voice. Boots a real emulation
    of the standalone RS-232 speech-synthesizer box via MAME (MC6802 CPU +
    real SC-01A chip) and records its actual output - the genuine period
    NRL text-to-phoneme firmware (4KB mask ROM, no host software involved)
    driving the same SC-01A chip this repo's own "votrax" engine emulates,
    so the difference from that engine is entirely in TNT's own hardware
    phoneme rules, not the synthesis core.

    No disk/OS to boot (unlike Textalker) - text is typed directly into
    the emulated RS-232 terminal and spoken almost immediately.

    Requires the Type 'N Talk firmware ROM and the SC-01A chip ROM (see
    scripts/fetch_roms.sh) mounted at /mame_roms/votrtnt/, plus the
    vendored MAME binary - silently unavailable if either is missing."""

    def get_voices(self) -> List[str]:
        return ["votrax_tnt"]

    def is_available(self) -> bool:
        if not mame_audio.MAME_BIN.exists():
            return False
        return all((_ROM_ROOT / rom).exists() for rom in _REQUIRED_ROMS)

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            sanitized = mame_audio.sanitize_text(text)
            wait_after = min(45.0, 3.0 + 0.3 * len(sanitized))
            seconds_to_run = int(5 + wait_after)

            with tempfile.TemporaryDirectory() as tmpdir:
                wav_path = Path(tmpdir) / "capture.wav"

                env = os.environ.copy()
                env["MAME_RS232_INPUT"] = sanitized + "\r"
                env["MAME_RS232_WAIT_AFTER"] = str(wait_after)
                env["MAME_RS232_BOOT_WAIT"] = "1.0"

                cmd = [
                    str(mame_audio.MAME_BIN), "votrtnt",
                    "-rompath", str(_ROM_ROOT),
                    "-rs232", "terminal",
                    "-video", "none", "-sound", "sdl", "-nothrottle",
                    "-seconds_to_run", str(seconds_to_run),
                    "-wavwrite", str(wav_path),
                    "-skip_gameinfo",
                    "-autoboot_script", str(_LUA_SCRIPT),
                ]
                subprocess.run(
                    cmd, env=env, capture_output=True,
                    timeout=seconds_to_run + 30, cwd=tmpdir,
                )
                if not wav_path.exists():
                    return False

                extracted = mame_audio.extract_speech_channel(wav_path)
                if extracted is None:
                    return False
                chan, sr = extracted

                return mame_audio.encode_mp3(chan, sr, output_path)
        except Exception:
            return False
