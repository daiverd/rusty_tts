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
    "votrpss/u-2.v3.c.bin",
    "votrpss/u-3.v3.c.bin",
    "votrpss/u-4.v3.1.bin",
    "votrpss/sc01a.bin",
]


class VotraxPersonalSpeechSystemEngine(BaseTTSEngine):
    """Authentic Votrax Personal Speech System (1982) voice. Boots a real
    emulation of the standalone Z80-based speech synthesizer via MAME
    (real firmware ROMs + real SC-01A chip) and records its actual output
    - genuine period phoneme/personality firmware driving the same SC-01A
    chip this repo's own "votrax" engine emulates, so the difference from
    that engine is entirely in the PSS's own hardware phoneme rules, not
    the synthesis core.

    No disk/OS to boot - text is typed directly into the machine's own
    built-in terminal keyboard. The real hardware's "Default Input Port"
    DIP switch defaults to expecting Serial/RS-232 input instead, which
    would silently ignore keyboard-path text by design (see votrpss.cpp),
    so native/mame-votrax/capture.lua forces that DIP to Parallel at boot.
    Speech only starts after the unit's own ~7.5s "System ready" power-on
    announcement finishes, which is cropped out of the recording.

    Requires the PSS firmware ROMs and the SC-01A chip ROM (see
    scripts/fetch_roms.sh) mounted at /mame_roms/votrpss/, plus the
    vendored MAME binary - silently unavailable if either is missing."""

    def get_voices(self) -> List[str]:
        return ["votrax_pss"]

    def is_available(self) -> bool:
        if not mame_audio.MAME_BIN.exists():
            return False
        return all((_ROM_ROOT / rom).exists() for rom in _REQUIRED_ROMS)

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            sanitized = mame_audio.sanitize_text(text)
            wait_after = min(45.0, 3.0 + 0.3 * len(sanitized))
            # The PSS's own fixed "System ready, Version 3.C" power-on
            # announcement takes ~7.5s to finish (measured empirically) -
            # boot_wait has to clear that before posting text, or the
            # characters arrive while it's still mid-announcement and get
            # dropped instead of queued.
            boot_wait = 9.0
            seconds_to_run = int(boot_wait + wait_after)

            with tempfile.TemporaryDirectory() as tmpdir:
                wav_path = Path(tmpdir) / "capture.wav"

                env = os.environ.copy()
                env["MAME_RS232_INPUT"] = sanitized + "\r"
                env["MAME_RS232_WAIT_AFTER"] = str(wait_after)
                env["MAME_RS232_BOOT_WAIT"] = str(boot_wait)
                env["MAME_VOTRAX_DSW1_PARALLEL"] = "1"

                cmd = [
                    str(mame_audio.MAME_BIN), "votrpss",
                    "-rompath", str(_ROM_ROOT),
                    "-video", "none", "-sound", "sdl", "-nothrottle",
                    "-seconds_to_run", str(seconds_to_run),
                    "-wavwrite", str(wav_path),
                    "-skip_gameinfo",
                    "-autoboot_script", str(_LUA_SCRIPT),
                ]
                proc = subprocess.run(
                    cmd, env=env, capture_output=True,
                    timeout=seconds_to_run + 30, cwd=tmpdir,
                )
                if not wav_path.exists():
                    return False

                min_start_seconds = mame_audio.parse_speech_marker(proc.stdout)
                extracted = mame_audio.extract_speech_channel(wav_path, min_start_seconds)
                if extracted is None:
                    return False
                chan, sr = extracted

                return mame_audio.encode_mp3(chan, sr, output_path)
        except Exception:
            return False
