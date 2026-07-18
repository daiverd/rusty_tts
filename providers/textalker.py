import os
import subprocess
import tempfile
from pathlib import Path
from typing import List

from . import BaseTTSEngine
from . import _mame_audio as mame_audio

_ROM_ROOT = mame_audio.ROM_ROOT
_DISK_IMAGE = _ROM_ROOT / "disks" / "Textalker_1.3.dsk"
_LUA_SCRIPT = Path(__file__).resolve().parent.parent / "native" / "mame-textalker" / "textalker_capture.lua"
_APPLECOMMANDER_JAR = Path("/opt/applecommander/ac.jar")

_REQUIRED_ROMS = [
    "apple2ee/341-0132-d.e12",
    "apple2ee/342-0265-a.chr",
    "apple2ee/342-0303-a.e8",
    "apple2ee/342-0304-a.e10",
    "apple2ee/341-0027-a.p5",
    "apple2ee/341-0028-a.rom",
]


def _build_hello_source(text: str) -> bytes:
    """A 3-line Applesoft program that becomes the disk's HELLO file (DOS
    3.3's autoexec - runs automatically on boot, no keyboard input
    needed). CHR$(4) is the classic Apple II trick for issuing a DOS
    command (BRUN) from inside a running program instead of the immediate
    prompt; Textalker's driver is written to hand control back to the
    caller afterward (verified empirically), so execution continues to
    the PRINT that actually speaks the phrase."""
    return (
        "10 D$ = CHR$(4)\n"
        "20 PRINT D$;\"BRUN TEXTALKER.BLIND\"\n"
        f"30 PRINT \"{text}\"\n"
    ).encode("ascii", errors="ignore")


def _write_hello(disk_path: Path, text: str) -> bool:
    source = _build_hello_source(text)
    # The stock disk already has a HELLO file; AppleCommander's -bas
    # import needs it gone first (ignore failure - absent is fine too).
    subprocess.run(
        ["java", "-jar", str(_APPLECOMMANDER_JAR), "-d", str(disk_path), "HELLO"],
        capture_output=True,
    )
    proc = subprocess.run(
        ["java", "-jar", str(_APPLECOMMANDER_JAR), "-bas", str(disk_path), "HELLO"],
        input=source, capture_output=True,
    )
    return proc.returncode == 0


class TextalkerEngine(BaseTTSEngine):
    """Authentic Echo II Plus / Textalker 1.3 voice. Boots a real Apple //e
    + Echo Plus (TMS5220C) emulation via MAME and records the genuine 1981
    Textalker driver's actual speech output - not a re-implementation of
    the chip fed synthetic data, the real historical text-to-phoneme logic
    and chip emulation together.

    The request text is baked directly into the disk's HELLO file (DOS
    3.3's autoexec, via AppleCommander) as a tiny Applesoft program that
    BRUNs the driver and PRINTs the phrase, so DOS runs it automatically
    on boot with no keyboard emulation needed - faster and immune to the
    dropped-keystroke/typed-character-echo issues an earlier natkeyboard-
    based version had.

    Requires proprietary Apple IIe/Disk II/Echo Plus ROMs plus the
    Textalker driver disk image (see scripts/fetch_roms.sh) mounted at
    /mame_roms, plus the vendored MAME binary and AppleCommander jar -
    silently unavailable if any of that is missing."""

    def get_voices(self) -> List[str]:
        return ["textalker"]

    def is_available(self) -> bool:
        if not mame_audio.MAME_BIN.exists() or not _DISK_IMAGE.exists():
            return False
        if not _APPLECOMMANDER_JAR.exists():
            return False
        return all((_ROM_ROOT / rom).exists() for rom in _REQUIRED_ROMS)

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            sanitized = mame_audio.sanitize_text(text)
            wait_after = min(60.0, 3.0 + 0.4 * len(sanitized))
            seconds_to_run = int(15 + wait_after)

            with tempfile.TemporaryDirectory() as tmpdir:
                tmp = Path(tmpdir)
                disk_copy = tmp / "session.dsk"
                disk_copy.write_bytes(_DISK_IMAGE.read_bytes())
                if not _write_hello(disk_copy, sanitized):
                    return False
                wav_path = tmp / "capture.wav"

                env = os.environ.copy()
                env["TEXTALKER_WAIT_AFTER"] = str(wait_after)

                cmd = [
                    str(mame_audio.MAME_BIN), "apple2ee",
                    "-rompath", str(_ROM_ROOT),
                    "-sl4", "echoiiplus",
                    "-flop1", str(disk_copy),
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
