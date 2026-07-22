import array
import asyncio
import os
import tempfile
import wave
from pathlib import Path
from typing import List

from . import BaseTTSEngine
from . import _mame_audio as mame_audio

# Standalone DoubleTalk PC emulator (sourced from the sibling doubletalk_pc
# repo, doubletalk/ subdir, at build time): the same
# vendored MAME 80C188EB core + original firmware ROM as the old MAME-based
# provider, minus MAME itself - no host PC boot, no GLaBIOS, no audio-mixer
# capture. Direct DAC capture at the card's own 10504Hz timer cadence,
# ~35-180x realtime, so per-request latency is milliseconds instead of the
# ~30s+ full-machine emulation this provider needed before.
_DTALK_BIN = Path(os.environ.get("DTALK_CLI", "/usr/local/bin/dtalk_cli"))
_ROM_PATH = mame_audio.ROM_ROOT / "doubletalkpc_isa" / "doubletalkpc.bin"


class DoubleTalkEngine(BaseTTSEngine):
    """Authentic RC Systems DoubleTalk PC (1990s ISA text-to-speech card)
    voice. Runs the card's real onboard 80C188EB CPU and original ~500KB
    firmware ROM (text-to-phonetics translation, dictionary, and LPC
    synthesis all included) in a standalone emulator - the MAME CPU core
    vendored without MAME - and captures the genuine firmware's own PCM
    output from its DAC port.

    Text is written to the card's host-facing TTS port exactly as a real
    host driver (e.g. Linux's dtlk.c) would: RDY-gated bytes, CR to start
    speech. Requires the DoubleTalk PC firmware ROM (archive.org dump -
    see scripts/fetch_roms.sh) mounted at /mame_roms; silently unavailable
    if the ROM or the dtalk_cli binary is missing. See the doubletalk_pc
    repo (doubletalk/ subdir, built into this image at build time) and the
    companion mame-doubletalk research repo for the reverse-engineering
    history."""

    def get_voices(self) -> List[str]:
        return ["doubletalk"]

    def is_available(self) -> bool:
        return _DTALK_BIN.exists() and _ROM_PATH.exists()

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            sanitized = mame_audio.sanitize_text(text)
            # ` stands in for Ctrl+A (0x01), the DoubleTalk control-code
            # prefix (see the RC Systems manual, "Embedded Codes" - e.g.
            # Ctrl+A 9 <n> sets speech rate). Substituted after
            # sanitize_text() rather than before, since that strips
            # anything outside printable ASCII and would eat a raw 0x01.
            sanitized = sanitized.replace("`", "\x01")

            with tempfile.TemporaryDirectory() as tmpdir:
                wav_path = Path(tmpdir) / "out.wav"
                proc = await asyncio.create_subprocess_exec(
                    str(_DTALK_BIN), str(_ROM_PATH), "say", sanitized, str(wav_path),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    # Synthesis runs ~35x realtime; even the 200-char cap's
                    # ~11s of speech finishes in well under a second. This
                    # is purely a hang guard.
                    await asyncio.wait_for(proc.communicate(), timeout=30.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    return False
                if not wav_path.exists():
                    return False

                with wave.open(str(wav_path), "rb") as w:
                    sr = w.getframerate()
                    raw = w.readframes(w.getnframes())
                if not raw:
                    return False

                # unsigned 8-bit -> signed 16-bit for the shared helpers
                chan = array.array("h", ((b - 128) << 8 for b in raw))

                bounds = mame_audio.trim_silence(chan, sr)
                if bounds is None:
                    return False
                start, end = bounds
                chan = chan[start:end]

                # A bit louder than the -20dBFS default other retro
                # providers use here: DoubleTalk measured noticeably
                # quieter than DECtalk at that target (see git history of
                # the MAME-based version of this provider). normalize_pcm
                # peak-limits, so this stays safely under 0dBFS.
                return mame_audio.encode_mp3(chan, sr, output_path, target_dbfs=-18.5)
        except Exception:
            return False
