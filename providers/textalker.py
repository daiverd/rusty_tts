import array
import os
import re
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import List, Optional, Tuple

from . import BaseTTSEngine

_MAME_BIN = Path("/opt/mame/mame")
_ROM_ROOT = Path("/mame_roms")
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

_MAX_TEXT_LEN = 200
_SILENCE_THRESHOLD = 400


def _sanitize(text: str) -> str:
    text = re.sub(r"[^\x20-\x7e]", " ", text).replace('"', "")
    text = text.strip()
    return text[:_MAX_TEXT_LEN] or "HELLO"


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


def _trim_silence(chan: array.array, sr: int, pad_s: float = 0.2) -> Optional[Tuple[int, int]]:
    win = max(1, sr // 20)
    n = len(chan)
    first = None
    last = None
    for i in range(0, n - win, win):
        seg = chan[i:i + win]
        m = max(abs(x) for x in seg)
        if m > _SILENCE_THRESHOLD:
            if first is None:
                first = i
            last = i + win
    if first is None:
        return None
    pad = int(pad_s * sr)
    return max(0, first - pad), min(n, last + pad)


def _extract_speech_channel(wav_path: Path, min_start_seconds: float = 0.0) -> Optional[Tuple[array.array, int]]:
    """MAME's -wavwrite mixes every sound device onto its own channel. The
    Echo Plus card has a TMS5220C plus two AY-3-8913 PSGs sharing the bus,
    so real speech ends up on one channel among several - disk-motor click
    noise and DC bias on the others stay within a narrow range, while
    speech clips to full scale and has a wide dynamic range. Picking the
    channel with the largest min/max spread reliably isolates it without
    hardcoding a channel index tied to this exact device enumeration."""
    with wave.open(str(wav_path), "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        sw = w.getsampwidth()
        n = w.getnframes()
        raw = w.readframes(n)
    if sw != 2 or n == 0:
        return None

    samples = array.array('h')
    samples.frombytes(raw)

    best_ch = None
    best_range = -1
    for c in range(ch):
        chan = samples[c::ch]
        rng = max(chan) - min(chan)
        if rng > best_range:
            best_range = rng
            best_ch = c

    if best_ch is None or best_range < 1000:
        return None

    chan = samples[best_ch::ch]

    # Everything before Textalker's fixed startup banner finishes is its
    # own installer text, not the requested phrase (see
    # textalker_capture.lua's "speech_starts_at_seconds" marker). Drop it
    # before silence-trimming.
    floor_sample = min(len(chan), max(0, int(min_start_seconds * sr)))
    chan = chan[floor_sample:]

    bounds = _trim_silence(chan, sr)
    if bounds is None:
        return None
    start, end = bounds
    return chan[start:end], sr


_SPEECH_MARKER_RE = re.compile(rb"speech_starts_at_seconds=([\d.]+)")


def _parse_speech_marker(mame_stdout: bytes) -> float:
    match = _SPEECH_MARKER_RE.search(mame_stdout)
    return float(match.group(1)) if match else 0.0


def _encode_mp3(chan: array.array, sr: int, output_path: Path) -> bool:
    ffmpeg_cmd = [
        "ffmpeg", "-f", "s16le", "-ar", str(sr), "-ac", "1",
        "-i", "pipe:0",
        "-af", "loudnorm",
        str(output_path), "-y",
    ]
    proc = subprocess.run(ffmpeg_cmd, input=chan.tobytes(), capture_output=True)
    return proc.returncode == 0 and output_path.exists()


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
        if not _MAME_BIN.exists() or not _DISK_IMAGE.exists():
            return False
        if not _APPLECOMMANDER_JAR.exists():
            return False
        return all((_ROM_ROOT / rom).exists() for rom in _REQUIRED_ROMS)

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            sanitized = _sanitize(text)
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
                    str(_MAME_BIN), "apple2ee",
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

                min_start_seconds = _parse_speech_marker(proc.stdout)
                extracted = _extract_speech_channel(wav_path, min_start_seconds)
                if extracted is None:
                    return False
                chan, sr = extracted

                return _encode_mp3(chan, sr, output_path)
        except Exception:
            return False
