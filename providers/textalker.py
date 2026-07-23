import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from . import BaseTTSEngine
from . import _mame_audio as mame_audio

_ROM_ROOT = mame_audio.ROM_ROOT
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


@dataclass(frozen=True)
class _Voice:
    disk: Path
    brun_target: str  # the BRUN'd filename on that disk
    banner_marker: str  # a fixed substring of that version's startup banner
    banner_timeout: float  # generous upper bound on real boot+banner time
    boot_leadin: float  # baseline seconds_to_run before adding text-dependent wait


# Textalker/TextTalker is Street Electronics' Echo-card screen reader,
# revised several times across the 1980s; each version has its own
# (slightly different) letter-to-sound rules, so they're exposed here as
# distinct voices rather than one fixed "textalker" voice - same idea as
# this repo's dectalk provider exposing multiple speakers, just driven by
# disk version instead of a command-line flag. Every voice runs through
# the identical real-hardware pipeline (MAME Apple //e + Echo Plus card,
# see native/mame-textalker/textalker_capture.lua) - only the disk image,
# the file BRUN'd from it, and the startup banner text used to detect
# "ready to speak" differ.
_VOICES: Dict[str, _Voice] = {
    "1.3": _Voice(
        disk=_ROM_ROOT / "disks" / "Textalker_1.3.dsk",
        brun_target="TEXTALKER.BLIND",
        banner_marker="COPYRIGHT 1981",
        banner_timeout=20.0,
        boot_leadin=15.0,
    ),
    # TextTalker 3.1.2 (1985/86, credited to Street/Levieux/Kory/Skutchan) -
    # a later, self-contained rewrite (see apple2-tcp/PLAN.md for the full
    # reverse-engineering history). Its own boot+banner sequence was found
    # to take up to ~29 real seconds (floppy-load-into-language-card time,
    # not sub-frame-transient as first assumed) - a longer, more generous
    # boot_leadin/banner_timeout than 1.3's, confirmed empirically this
    # session via apple2-tcp/tools/tt312_tts.py.
    "3.1.2": _Voice(
        disk=_ROM_ROOT / "disks" / "Textalker_3.1.2.dsk",
        brun_target="TEXTALKER",
        banner_marker="VERSION 3.1.2",
        banner_timeout=35.0,
        boot_leadin=32.0,
    ),
}


def _build_hello_source(voice: _Voice, text: str) -> bytes:
    """A 3-line Applesoft program that becomes the disk's HELLO file (DOS
    3.3's autoexec - runs automatically on boot, no keyboard input
    needed). CHR$(4) is the classic Apple II trick for issuing a DOS
    command (BRUN) from inside a running program instead of the immediate
    prompt; Textalker's driver is written to hand control back to the
    caller afterward (verified empirically), so execution continues to
    the PRINT that actually speaks the phrase."""
    return (
        "10 D$ = CHR$(4)\n"
        f"20 PRINT D$;\"BRUN {voice.brun_target}\"\n"
        f"30 PRINT \"{text}\"\n"
    ).encode("ascii", errors="ignore")


def _write_hello(voice: _Voice, disk_path: Path, text: str) -> bool:
    source = _build_hello_source(voice, text)
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
    """Authentic Street Electronics Echo Plus / Textalker voice(s). Boots a
    real Apple //e + Echo Plus (TMS5220C) emulation via MAME and records
    the genuine period Textalker/TextTalker driver's actual speech output
    - not a re-implementation of the chip fed synthetic data, the real
    historical text-to-phoneme logic and chip emulation together.

    Textalker was revised several times across the 1980s with different
    letter-to-sound rules each time; each disk version is exposed as its
    own voice (see _VOICES) rather than a single fixed voice, since
    Textalker itself has no notion of "voice presets" the way later
    engines do.

    The request text is baked directly into the disk's HELLO file (DOS
    3.3's autoexec, via AppleCommander) as a tiny Applesoft program that
    BRUNs the driver and PRINTs the phrase, so DOS runs it automatically
    on boot with no keyboard emulation needed - faster and immune to the
    dropped-keystroke/typed-character-echo issues an earlier natkeyboard-
    based version had.

    Requires proprietary Apple IIe/Disk II/Echo Plus ROMs plus at least
    one Textalker driver disk image (see scripts/fetch_roms.sh) mounted at
    /mame_roms, plus the vendored MAME binary and AppleCommander jar -
    voices whose disk is missing are silently left out of get_voices(),
    and the whole engine is unavailable if none of them are present."""

    def _available_voices(self) -> List[str]:
        return [name for name, voice in _VOICES.items() if voice.disk.exists()]

    def get_voices(self) -> List[str]:
        return self._available_voices()

    def is_available(self) -> bool:
        if not mame_audio.MAME_BIN.exists() or not _APPLECOMMANDER_JAR.exists():
            return False
        if not all((_ROM_ROOT / rom).exists() for rom in _REQUIRED_ROMS):
            return False
        return len(self._available_voices()) > 0

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            selected = _VOICES.get(voice)
            if selected is None or not selected.disk.exists():
                return False

            sanitized = mame_audio.sanitize_text(text)
            wait_after = min(60.0, 3.0 + 0.4 * len(sanitized))
            seconds_to_run = int(selected.boot_leadin + wait_after)

            with tempfile.TemporaryDirectory() as tmpdir:
                tmp = Path(tmpdir)
                disk_copy = tmp / "session.dsk"
                disk_copy.write_bytes(selected.disk.read_bytes())
                if not _write_hello(selected, disk_copy, sanitized):
                    return False
                wav_path = tmp / "capture.wav"

                env = os.environ.copy()
                env["TEXTALKER_WAIT_AFTER"] = str(wait_after)
                env["TEXTALKER_BANNER_MARKER"] = selected.banner_marker
                env["TEXTALKER_BANNER_TIMEOUT"] = str(selected.banner_timeout)

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
