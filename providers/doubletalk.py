import array
import os
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import List, Optional, Tuple

from . import BaseTTSEngine
from . import _mame_audio as mame_audio

_ROM_ROOT = mame_audio.ROM_ROOT
_LUA_SCRIPT = Path(__file__).resolve().parent.parent / "native" / "mame-doubletalk" / "capture.lua"

_REQUIRED_ROMS = [
    "doubletalkpc_isa/doubletalkpc.bin",
    "pcv20/glabios_0.2.4_vt.rom",
]

# Channel index (0-based) of the DoubleTalk card's own audio in the
# -wavwrite recording. MAME assigns one channel per SPEAKER device, in
# machine_config declaration order: the pcv20 host machine's own PC
# speaker is declared first (channel 1 / index 0), the DoubleTalk card's
# DAC is declared second (channel 2 / index 1) - see doubletalkpc.cpp's
# device_add_mconfig and DOUBLETALK.md. This is a FIXED index, not
# auto-detected: _mame_audio.extract_speech_channel()'s "pick the channel
# with the largest dynamic range" heuristic (which works for the other
# MAME-based providers here) picked the wrong channel for this card - a
# full-scale GLaBIOS boot beep on the host speaker channel can have more
# range than DoubleTalk's own speech, regardless of what text was sent
# (confirmed: identical audio for different input text, because the
# "speech" being extracted was actually just the fixed boot beep).
_DOUBLETALK_CHANNEL = 1


def _extract_doubletalk_channel(wav_path: Path) -> Optional[Tuple[array.array, int]]:
    with wave.open(str(wav_path), "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        sw = w.getsampwidth()
        n = w.getnframes()
        raw = w.readframes(n)
    if sw != 2 or n == 0 or ch <= _DOUBLETALK_CHANNEL:
        return None

    samples = array.array('h')
    samples.frombytes(raw)
    chan = samples[_DOUBLETALK_CHANNEL::ch]

    # The card's DAC outputs a fixed, deterministic full-scale ~100ms click
    # at power-on, every single capture, well before capture.lua's SEND_AT
    # delay - it's a hardware/emulation power-on transient, not audio. Since
    # it's loud, trim_silence()'s "first non-silent window" would otherwise
    # anchor on the click itself and keep it (plus the real silence between
    # it and actual speech) in the final clip. Skip past it before trimming.
    startup_click_samples = int(0.15 * sr)
    chan = chan[startup_click_samples:]

    bounds = mame_audio.trim_silence(chan, sr)
    if bounds is None:
        return None
    start, end = bounds
    return chan[start:end], sr


class DoubleTalkEngine(BaseTTSEngine):
    """Authentic RC Systems DoubleTalk PC (1990s ISA text-to-speech card)
    voice. Boots a real emulation of a generic PC (V20 CPU, GLaBIOS - an
    open-source BIOS, since the real IBM BIOS is copyrighted and not
    needed here) with the DoubleTalk card attached to an ISA slot, and
    records the genuine firmware's own actual speech output - not a
    reimplementation, the real onboard 80C188EB CPU running the card's
    original ~500KB ROM (text-to-phonetics translation, dictionary, and
    LPC synthesis all included), captured from its own PCM sample output.

    Text is written directly to the card's host-facing TTS port (RDY-
    gated, matching how a real host driver like Linux's dtlk.c behaves) -
    no OS, disk, or keyboard device involved, so speech starts almost
    immediately once the host PC itself finishes booting.

    Requires the DoubleTalk PC firmware ROM (archive.org dump - see
    scripts/fetch_roms.sh) and GLaBIOS (open-source, GPL3) mounted at
    /mame_roms, plus the vendored MAME binary - silently unavailable if
    either is missing. See native/mame-doubletalk/capture.lua and the
    companion doubletalk-pc/mame-doubletalk research repos (referenced in
    scripts/fetch_roms.sh) for the full reverse-engineering history behind
    this provider."""

    def get_voices(self) -> List[str]:
        return ["doubletalk"]

    def is_available(self) -> bool:
        if not mame_audio.MAME_BIN.exists():
            return False
        return all((_ROM_ROOT / rom).exists() for rom in _REQUIRED_ROMS)

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            sanitized = mame_audio.sanitize_text(text)
            # ` stands in for Ctrl+A (0x01), the DoubleTalk control-code
            # prefix (see the RC Systems manual, "Embedded Codes" - e.g.
            # Ctrl+A 9 <n> sets speech rate). Substituted after
            # sanitize_text() rather than before, since that strips
            # anything outside printable ASCII and would eat a raw 0x01.
            sanitized = sanitized.replace("`", "\x01")
            # capture.lua detects real completion itself (card's read/write
            # buffer pointers equal + settle + audio tail) and exits early -
            # this is just the hard timeout fallback, so it only needs to be
            # generously larger than worst-case synthesis time, not tuned.
            wait_after = min(90.0, 20.0 + 0.5 * len(sanitized))
            seconds_to_run = int(wait_after) + 15

            with tempfile.TemporaryDirectory() as tmpdir:
                wav_path = Path(tmpdir) / "capture.wav"

                env = os.environ.copy()
                env["DOUBLETALK_INPUT"] = sanitized
                env["DOUBLETALK_WAIT_AFTER"] = str(wait_after)

                cmd = [
                    str(mame_audio.MAME_BIN), "pcv20",
                    "-bios", "glabios_0.24",
                    "-isa1", "", "-isa2", "", "-isa3", "", "-isa4", "", "-isa5", "", "-kbd", "",
                    "-isa6", "doubletalkpc",
                    "-rompath", str(_ROM_ROOT),
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

                extracted = _extract_doubletalk_channel(wav_path)
                if extracted is None:
                    return False
                chan, sr = extracted

                # A bit louder than the -20dBFS default other MAME-backed
                # providers use here: DoubleTalk's captured audio measured
                # noticeably quieter than DECtalk's at that target (-20.0
                # mean/-1.9 peak dB vs DECtalk's -17.7/-0.4). normalize_pcm
                # already peak-limits, so this stays safely under 0dBFS.
                return mame_audio.encode_mp3(chan, sr, output_path, target_dbfs=-18.5)
        except Exception:
            return False
