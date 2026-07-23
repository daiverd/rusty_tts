import asyncio
from pathlib import Path
from typing import List

from . import BaseTTSEngine
from .mp3_encoder import encode_pcm_to_mp3
from ._smoothtalker_engine import core

# Proprietary engine snapshot (c. 1990 First Byte SmoothTalker/SBTALKER,
# bundled with Creative Labs' Dr. Sbaitso) - not redistributed by this repo,
# see roms/smoothtalker/PROVENANCE.md. Same gitignored-but-baked-into-image
# convention as roms/sp0256.bin, roms/sc01a.bin, etc.
_IMAGE_PATH = Path(__file__).resolve().parent.parent / "roms" / "smoothtalker" / "engine.bin"

# The engine's native rate (8475 Hz) is an oddball not every downstream
# consumer likes; resample to something conventional before MP3 encoding.
_OUT_RATE = 22050


def _split_text(text: str, limit: int = None) -> List[str]:
    """Break text into pieces the engine can accept in one call (255-byte
    length-prefixed buffer). Splits at the strongest available break -
    sentence, then clause, then word - so prosody restarts land at natural
    boundaries instead of mid-phrase. Ported from the NVDA driver's
    _splitText."""
    if limit is None:
        limit = core.MAX_TEXT
    text = text.strip()
    if not text:
        return []
    out = []
    while len(text) > limit:
        window = text[:limit + 1]
        cut = -1
        for seps in ('.!?', ',;:'):
            best = -1
            for sep in seps:
                idx = window.rfind(sep + ' ')
                if idx > best:
                    best = idx
            if best > limit // 4:
                cut = best + 1
                break
        if cut < 0:
            cut = window.rfind(' ')
        if cut <= 0:
            cut = limit
        out.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        out.append(text)
    return [c for c in out if c]


class SmoothTalkerEngine(BaseTTSEngine):
    """First Byte SmoothTalker / SBTALKER 3.5 (1990), the DOS engine behind
    Creative Labs' Dr. Sbaitso. Runs a captured, already-resident memory
    snapshot of the real 16-bit engine under the Unicorn CPU emulator - no
    DOS emulation, no DOSBox, no Windows/Wine - and captures its genuine
    Sound Blaster DSP output. See providers/_smoothtalker_engine/core.py
    (ported from the smoothtalker NVDA addon) for the emulation details."""

    def get_voices(self) -> List[str]:
        return ["default"]

    def is_available(self) -> bool:
        return _IMAGE_PATH.exists()

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            return await asyncio.to_thread(self._synthesize_sync, text, output_path)
        except Exception:
            return False

    def _synthesize_sync(self, text: str, output_path: Path) -> bool:
        pieces = _split_text(text)
        if not pieces:
            return False

        # A fresh Engine/emulator per request rather than a shared resident
        # instance: Unicorn contexts aren't safe to share across concurrent
        # requests, and building one is cheap (~ms) next to the DOS TSR's
        # own synthesis time.
        engine = core.Engine(str(_IMAGE_PATH))
        resampler = None
        pcm16 = bytearray()
        for piece in pieces:
            pcm8, rate = engine.speak(piece)
            if not pcm8:
                continue
            if resampler is None:
                resampler = core.Resampler(rate, _OUT_RATE)
            pcm16 += resampler.feed(core.to_pcm16(pcm8))

        if not pcm16:
            return False

        return encode_pcm_to_mp3(bytes(pcm16), _OUT_RATE, 1, output_path)
