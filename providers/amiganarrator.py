"""
AmigaNarrator TTS Engine

Runs the real AmigaOS 1.x `narrator.device` / `translator.library` (Mark
Barton & Joseph Katz, 1984 - the synthesizer behind `SAY` on every classic
Amiga) via nicodex/AmigaNarrator, a native Linux port that hosts the actual
680x0 Amiga binaries under Musashi (a pure-C 68k CPU emulator), trapping
just enough exec.library calls to run them standalone - no Wine, no VM, no
MAME. Same "real vendor code, instruction-level-emulated, thin native
harness" shape as providers/wintalker.py and providers/monologue.py. See
~/src/speech/AmigaNarrator/PLAN.md.

Two-stage pipeline, same as the real Amiga SAY command:
  text -> `translator` (English -> phonetic string) -> `narrator`
  (phonetic string -> raw PCM, S8 mono @ 22200 Hz)

narrator.device/translator.library are proprietary Commodore/Amiga OS
components, not baked into the image - mounted at runtime from
roms/amiganarrator/ (gitignored, see its PROVENANCE.md), same convention
as providers/keynote.py.
"""

import array
import asyncio
import os
import re
from pathlib import Path
from typing import List

from . import BaseTTSEngine
from .mp3_encoder import encode_pcm_to_mp3

_BIN_DIR = Path(os.environ.get("AMIGANARRATOR_BIN_DIR", "/opt/amiganarrator"))
_TRANSLATOR_BIN = _BIN_DIR / "translator"
_NARRATOR_BIN = _BIN_DIR / "narrator"

_ROMS_DIR = Path(__file__).resolve().parent.parent / "roms" / "amiganarrator"
_LIB_PATH = _ROMS_DIR / "translator.library"
_DEV_PATH = _ROMS_DIR / "narrator.device"

_SAMPLE_RATE = 22200

# (sex, mode) argv values narrator's -s/-m options take: sex 0=male
# 1=female, mode 0=natural 1=robotic.
_VOICES = {
    "male": ("0", "0"),
    "female": ("1", "0"),
    "male-robot": ("0", "1"),
    "female-robot": ("1", "1"),
}


def _sanitize(text: str) -> str:
    # translator.library is an English-text-to-phoneme table lookup;
    # non-ASCII input risks garbage phonemes rather than a clean error.
    return re.sub(r"[^\x20-\x7e]", " ", text).strip() or "hello"


def _widen_s8_to_s16(pcm_s8: bytes) -> bytes:
    # narrator emits signed 8-bit PCM; lameenc only accepts 16-bit.
    samples = array.array('b')
    samples.frombytes(pcm_s8)
    return array.array('h', (s << 8 for s in samples)).tobytes()


class AmigaNarratorEngine(BaseTTSEngine):
    """AmigaOS narrator.device/translator.library, run via Musashi 68k
    CPU emulation (no Wine/VM/MAME)."""

    def get_voices(self) -> List[str]:
        return list(_VOICES.keys())

    def is_available(self) -> bool:
        return (
            _TRANSLATOR_BIN.exists() and _NARRATOR_BIN.exists()
            and _LIB_PATH.exists() and _DEV_PATH.exists()
        )

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        sex, mode = _VOICES.get(voice, _VOICES["male"])
        text = _sanitize(text)

        try:
            phonetic = await self._run(
                [str(_TRANSLATOR_BIN), "-l", str(_LIB_PATH), text]
            )
            if phonetic is None:
                return False
            phonetic = phonetic.decode("ascii", "replace").strip()
            if not phonetic:
                return False

            pcm_s8 = await self._run(
                [str(_NARRATOR_BIN), "-d", str(_DEV_PATH), "-s", sex, "-m", mode, phonetic]
            )
            if not pcm_s8:
                return False

            pcm_s16 = _widen_s8_to_s16(pcm_s8)
            return encode_pcm_to_mp3(pcm_s16, _SAMPLE_RATE, 1, output_path)
        except Exception:
            return False

    @staticmethod
    async def _run(cmd: List[str]):
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        except asyncio.TimeoutError:
            proc.kill()
            return None
        return stdout
