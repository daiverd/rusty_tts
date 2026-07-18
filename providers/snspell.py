import struct
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import BaseTTSEngine, run_tts_pipeline_stdin_raw
from ._vocab_lookup import resolve_tokens, tokenize

# MASTER_CLOCK/80 for the TMC0281 (== TMS5100) chip used by every validated
# Speak & Spell region - see snspell.cpp's sns_tmc0281() machine config and
# tms5110_device::device_start()'s stream_alloc(). Must match
# native/retrochip/main.cpp's run_tms5110() sample rate.
_SAMPLE_RATE = 8000

_ROMS_ROOT = Path(__file__).resolve().parent.parent / "roms" / "snspell"

# Only these regions have been validated to produce correct, real English
# vocabulary from the ROM's embedded word-list table (see _parse_vocab_rom's
# docstring for why). Two-ROM filename pairs, in load order.
_REGIONS: Dict[str, Tuple[str, str]] = {
    "us": ("tmc0351n2l.bin", "tmc0352n2l.bin"),
    "us_1978": ("tmc0351nl.bin", "tmc0352nl.bin"),
    "uk": ("cd2303.bin", "cd2304.bin"),
    "jp": ("cd2321.bin", "cd2322.bin"),
}


def _rom_paths(voice: str) -> Optional[Tuple[Path, Path]]:
    pair = _REGIONS.get(voice)
    if pair is None:
        return None
    region_dir = _ROMS_ROOT / voice
    return region_dir / pair[0], region_dir / pair[1]


def _parse_vocab_rom(vsm: bytes) -> Dict[str, int]:
    """Walk the 4 built-in difficulty-level word lists baked into a Speak &
    Spell vocabulary ROM pair, returning a {WORD: lpc_address} map.

    This is a from-scratch reimplementation of the ROM's own embedded
    lookup-table structure (word-count byte + list-pointer per level, then
    per-word letter/speech-address entries with a 6-bit-per-letter
    encoding and a terminator bit marking the last letter), informed by the
    public documentation of this format at github.com/BrerDawg/ti_lpc
    (GPLv2) - not copied from it.
    """
    words: Dict[str, int] = {}
    for level in range(4):
        word_count = vsm[level]
        list_addr = vsm[4 + level * 2] | (vsm[4 + level * 2 + 1] << 8)
        for i in range(0, word_count, 2):
            word_ptr = vsm[list_addr + i] | (vsm[list_addr + i + 1] << 8)
            letters = []
            speech_addr = None
            for j in range(8):
                b = vsm[word_ptr + j]
                ch = (b & 0x3F) + 0x41
                if ch == ord('['):
                    ch = ord("'")
                letters.append(chr(ch))
                if b & 0x40:
                    speech_addr = vsm[word_ptr + j + 1] | (vsm[word_ptr + j + 2] << 8)
                    break
            if speech_addr is not None:
                words[''.join(letters)] = speech_addr
    return words


def _get_ptr(vsm: bytes, offs: int) -> int:
    return vsm[offs] | (vsm[offs + 1] << 8)


def _parse_system_phrases(vsm: bytes) -> Dict[Tuple[str, ...], int]:
    """The 4 word lists (_parse_vocab_rom) are only the spelling-game
    vocabulary. Every ROM also has a second, fixed-offset table right
    before it holding the toy's own UI phrases - the 26 letters, digits
    0-9 plus "10", and game phrases like "SPELL"/"WRONG"/"THAT IS
    CORRECT" - needed to actually reproduce what the real toy says beyond
    the spelling words themselves. Offsets/order derived the same way as
    _parse_vocab_rom (see that function's docstring)."""
    phrases: Dict[Tuple[str, ...], int] = {}
    pp = 0xc
    for i in range(26):
        phrases[(chr(0x41 + i),)] = _get_ptr(vsm, pp)
        pp += 2

    phrases[("BEEP",)] = _get_ptr(vsm, pp)
    pp += 2

    for i in range(10):
        phrases[(str(i),)] = _get_ptr(vsm, pp)
        pp += 2
    phrases[("TEN",)] = _get_ptr(vsm, pp)
    pp += 2

    for label in ["THAT IS CORRECT", "YOU ARE CORRECT", "THAT IS RIGHT", "YOU ARE RIGHT"]:
        phrases[tuple(label.split())] = _get_ptr(vsm, pp)
        pp += 2

    for label in ["WRONG", "THAT IS INCORRECT", "SPELL", "NOW SPELL", "NEXT SPELL", "NOW TRY", "TRY"]:
        p2 = _get_ptr(vsm, pp)
        phrases[tuple(label.split())] = _get_ptr(vsm, p2)
        pp += 2

    for label in ["SAY IT", "I WIN", "YOU WIN"]:
        phrases[tuple(label.split())] = _get_ptr(vsm, pp)
        pp += 2

    p2 = _get_ptr(vsm, pp)
    phrases[("HERE", "IS", "YOUR", "SCORE")] = _get_ptr(vsm, p2)
    pp += 2

    phrases[("PERFECT", "SCORE")] = _get_ptr(vsm, pp)
    pp += 2

    return phrases


def _load_vocab(voice: str) -> Optional[Dict[Tuple[str, ...], int]]:
    paths = _rom_paths(voice)
    if paths is None:
        return None
    rom0_path, rom1_path = paths
    if not rom0_path.exists() or not rom1_path.exists():
        return None
    try:
        vsm = rom0_path.read_bytes() + rom1_path.read_bytes()
        entries: Dict[Tuple[str, ...], int] = {
            (word,): addr for word, addr in _parse_vocab_rom(vsm).items()
        }
        entries.update(_parse_system_phrases(vsm))
        return entries
    except Exception:
        return None


class SnSpellEngine(BaseTTSEngine):
    """TI Speak & Spell (TMS5100/TMC0281 chip) vocabulary-word voice, driven
    by a standalone port of MAME's tms5110 core (native/retrochip) fed real
    genuine vocabulary ROM dumps.

    Unlike this project's tms5220 engine, the TMS5100/5110 family used by
    the Speak & Spell has no live external-frame injection mode here - only
    its VSM (vocabulary ROM) word-lookup path is implemented, matching how
    the real toy actually worked. This means synthesis is **word-lookup
    only, not open text**: every word (or, for the toy's own UI phrases
    like "SPELL"/"WRONG"/"THAT IS CORRECT", every matched multi-word
    phrase) in the input must appear verbatim (case-insensitively) in the
    ROM's own built-in tables - the spelling-game word list plus letters
    A-Z, digits 0-9/TEN, and the toy's fixed UI phrases - or synthesis
    fails outright. Matching is greedy longest-phrase-first, left to
    right. There is no fallback to any other synthesis path and no
    partial-sentence output.

    Vocabulary entries can also be addressed directly by 1-based position
    (`#1`, `#30`, ...) instead of by name, freely mixed with plain words in
    the same request (e.g. "#1 wrong" or "#1 #30 goodbye") - see
    providers/_vocab_lookup.py.
    """

    def __init__(self, config: Dict = None):
        super().__init__(config)
        self._vocab_cache: Dict[str, Dict[Tuple[str, ...], int]] = {}

    def get_voices(self) -> List[str]:
        return list(_REGIONS.keys())

    def is_available(self) -> bool:
        try:
            return any(self._vocab_for(voice) for voice in _REGIONS)
        except Exception:
            return False

    def _vocab_for(self, voice: str) -> Optional[Dict[Tuple[str, ...], int]]:
        if voice not in self._vocab_cache:
            vocab = _load_vocab(voice)
            if not vocab:
                return None
            self._vocab_cache[voice] = vocab
        return self._vocab_cache[voice]

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            vocab = self._vocab_for(voice)
            if not vocab:
                return False

            tokens = tokenize(text)
            if not tokens:
                return False

            addresses = resolve_tokens(tokens, vocab)
            if addresses is None:
                return False

            addr_bytes = b"".join(struct.pack(">H", addr) for addr in addresses)

            retrochip_cmd = [
                "retrochip", "--chip", "tms5110",
                "--rom", str(_concat_rom_pair(voice)),
            ]
            return run_tts_pipeline_stdin_raw(
                retrochip_cmd, addr_bytes, output_path,
                sample_rate=_SAMPLE_RATE, channels=1
            )
        except Exception:
            return False


_CONCAT_ROM_CACHE: Dict[str, Path] = {}


def _concat_rom_pair(voice: str) -> Path:
    """retrochip's --rom flag expects a single flat VSM byte array (see
    tms5110.h's set_vocab_rom); the real ROM pair is two separate mask ROM
    dumps concatenated in address order, same as _parse_vocab_rom's `vsm`.
    Cache the concatenated file next to the source ROMs so we only write it
    once per process."""
    if voice in _CONCAT_ROM_CACHE and _CONCAT_ROM_CACHE[voice].exists():
        return _CONCAT_ROM_CACHE[voice]

    rom0_path, rom1_path = _rom_paths(voice)
    out_path = rom0_path.parent / "_combined.vsm"
    if not out_path.exists():
        out_path.write_bytes(rom0_path.read_bytes() + rom1_path.read_bytes())
    _CONCAT_ROM_CACHE[voice] = out_path
    return out_path
