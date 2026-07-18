from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import BaseTTSEngine, run_tts_pipeline_stdin_raw
from ._vocab_lookup import resolve_tokens, tokenize

# No MAME driver clocks this chip for the real TSI Speech+ calculator (see
# native/retrochip/main.cpp's run_s14001a) - 20000Hz is the documented clock
# for this chip family elsewhere (Atari wolfpack.cpp's S14001A instantiation).
_SAMPLE_RATE = 20000

_ROM_PATH = Path(__file__).resolve().parent.parent / "roms" / "tsispeech" / "tsispeechplusmaskrom.bin"

# Word -> 6-bit index, from Sean Riddle's logic-analyzer capture of a real
# TSI Speech+ calculator (https://seanriddle.com/tsispeechplusrom.txt).
# Multi-word entries (e.g. "TIMES MINUS") are spoken as a single word slot
# on the real hardware, not two separate ones. Index 13 ("silence") and
# 25-31 (unused) are degenerate/non-speakable entries, excluded here -
# same precedent as snspell.py excluding its own "BEEP"/tone entries from
# open vocabulary matching.
_WORDS: Dict[Tuple[str, ...], int] = {
    ("OH",): 0,
    ("ONE",): 1,
    ("TWO",): 2,
    ("THREE",): 3,
    ("FOUR",): 4,
    ("FIVE",): 5,
    ("SIX",): 6,
    ("SEVEN",): 7,
    ("EIGHT",): 8,
    ("NINE",): 9,
    ("TIMES", "MINUS"): 10,
    ("EQUALS",): 11,
    ("PERCENT",): 12,
    ("LOW",): 14,
    ("OVER",): 15,
    ("ROOT",): 16,
    ("M",): 17,
    ("TIMES",): 18,
    ("POINT",): 19,
    ("OVERFLOW",): 20,
    ("MINUS",): 21,
    ("PLUS",): 22,
    ("CLEAR",): 23,
    ("SWAP",): 24,
}


def _load_rom() -> Optional[bytes]:
    if not _ROM_PATH.exists():
        return None
    try:
        data = _ROM_PATH.read_bytes()
        return data if data else None
    except Exception:
        return None


class S14001aCalculatorEngine(BaseTTSEngine):
    """TSI/Silicon Systems S14001A (1976 TSI Speech+ talking calculator)
    voice, driven by a standalone port of MAME's s14001a core
    (native/retrochip) fed the real calculator's genuine 2K mask ROM.

    This is a fixed, tiny built-in vocabulary chip: it speaks a word by its
    6-bit index directly (no vocabulary-ROM pointer lookup like the Speak &
    Spell's TMS5100). Synthesis here is **word-lookup only, not open
    text**: every word (or multi-word entry like "times minus") in the
    input must appear verbatim (case-insensitively) in the table above, or
    synthesis fails outright. Matching is greedy longest-phrase-first, left
    to right; entries can also be addressed directly by 1-based position
    (`#1`, `#22`, ...), freely mixed with plain words (see
    providers/_vocab_lookup.py). There is no fallback to any other
    synthesis path and no partial-sentence output.
    """

    def __init__(self, config: Dict = None):
        super().__init__(config)
        self._rom_cache: Optional[bytes] = None
        self._rom_loaded = False

    def get_voices(self) -> List[str]:
        return ["calculator"]

    def is_available(self) -> bool:
        return self._rom() is not None

    def _rom(self) -> Optional[bytes]:
        if not self._rom_loaded:
            self._rom_cache = _load_rom()
            self._rom_loaded = True
        return self._rom_cache

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            rom = self._rom()
            if rom is None:
                return False

            tokens = tokenize(text)
            if not tokens:
                return False

            indices = resolve_tokens(tokens, _WORDS)
            if indices is None:
                return False

            index_bytes = bytes(indices)

            retrochip_cmd = [
                "retrochip", "--chip", "s14001a",
                "--rom", str(_ROM_PATH),
            ]
            return run_tts_pipeline_stdin_raw(
                retrochip_cmd, index_bytes, output_path,
                sample_rate=_SAMPLE_RATE, channels=1
            )
        except Exception:
            return False
