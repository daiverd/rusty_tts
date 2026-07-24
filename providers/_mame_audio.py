"""Shared helpers for providers that boot a real machine in a vendored MAME
build and capture its genuine audio output via -wavwrite (see
providers/textalker.py, votrax_tnt.py, votrax_pss.py). Not a provider
itself - no BaseTTSEngine here, just the WAV post-processing these engines
all need.
"""
import array
import re
import wave
from pathlib import Path
from typing import Optional, Tuple

from .mp3_encoder import encode_pcm_to_mp3

MAME_BIN = Path("/opt/mame/mame")
ROM_ROOT = Path("/mame_roms")

_SILENCE_THRESHOLD = 400
_MAX_TEXT_LEN = 200


def sanitize_text(text: str) -> str:
    text = re.sub(r"[^\x20-\x7e]", " ", text).replace('"', "")
    text = text.strip()
    return text[:_MAX_TEXT_LEN] or "HELLO"


def trim_silence(chan: array.array, sr: int, pad_s: float = 0.2) -> Optional[Tuple[int, int]]:
    win = max(1, sr // 20)
    n = len(chan)
    window_maxes = [max(abs(x) for x in chan[i:i + win]) for i in range(0, n - win, win)]
    if not window_maxes:
        return None

    # Some machines (e.g. the Votrax PSS - see votrax_pss.py) output a
    # constant nonzero idle bias on their speech channel instead of true
    # near-zero silence, well above the fixed _SILENCE_THRESHOLD that's
    # calibrated for machines that do go quiet. Estimate that per-clip idle
    # floor (10th percentile of window peaks - most of a clip's windows are
    # idle, not mid-speech) and raise the threshold above it when needed, so
    # idle hum isn't mistaken for the start/end of real speech.
    noise_floor = sorted(window_maxes)[len(window_maxes) // 10]
    threshold = max(_SILENCE_THRESHOLD, int(noise_floor * 1.5))

    first = None
    last = None
    for idx, m in enumerate(window_maxes):
        if m > threshold:
            i = idx * win
            if first is None:
                first = i
            last = i + win
    if first is None:
        return None
    pad = int(pad_s * sr)
    return max(0, first - pad), min(n, last + pad)


def extract_speech_channel(wav_path: Path, min_start_seconds: float = 0.0) -> Optional[Tuple[array.array, int]]:
    """MAME's -wavwrite mixes every sound device onto its own channel -
    these machines all have more than one (PSGs, beepers, etc. alongside
    the actual speech chip). The channel with the largest dynamic range is
    picked automatically rather than hardcoding an index tied to a
    specific device enumeration, since real speech clips towards full
    scale while incidental noise (disk motor clicks, DC bias) stays in a
    narrow range.

    min_start_seconds crops out anything before that point (e.g. a fixed
    startup banner, or typed-character echo) - see each engine's Lua
    script for how it's determined."""
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

    floor_sample = min(len(chan), max(0, int(min_start_seconds * sr)))
    chan = chan[floor_sample:]

    bounds = trim_silence(chan, sr)
    if bounds is None:
        return None
    start, end = bounds
    return chan[start:end], sr


_SPEECH_MARKER_RE = re.compile(rb"speech_starts_at_seconds=([\d.]+)")


def parse_speech_marker(mame_stdout: bytes) -> float:
    match = _SPEECH_MARKER_RE.search(mame_stdout)
    return float(match.group(1)) if match else 0.0


def encode_mp3(chan: array.array, sr: int, output_path: Path, target_dbfs: float = -20.0) -> bool:
    return encode_pcm_to_mp3(chan.tobytes(), sr, 1, output_path, normalize=True, target_dbfs=target_dbfs)
