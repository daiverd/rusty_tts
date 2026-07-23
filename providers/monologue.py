"""
Monologue / ProVoice TTS Engine

Runs the real First Byte "Monologue" (ProVoice) 16-bit Windows 3.1 speech
engine (FB_SPCH.DLL, FB_TIMER.DLL, FB_NGN.EXE, and the FB_22K16/FB_11K8
voice-table DLLs) under a small Win16-on-Unicorn loader/emulator
(providers/_monologue_engine/, ported from the monologue16-NVDA add-on) -
no Windows/Wine/DOS emulation, no subprocess, in-process pure Python.

Same First Byte engine family as providers/smoothtalker.py, but here the
real NE-format DLLs are loaded and linked at runtime (general Win16 loader)
rather than resuming a captured DOS TSR memory snapshot.
"""

import asyncio
from pathlib import Path
from typing import List

from . import BaseTTSEngine
from .mp3_encoder import encode_pcm_to_mp3
from ._monologue_engine import core

# Proprietary engine binaries (c. 1990s First Byte Monologue/ProVoice) - not
# redistributed by this repo, see roms/monologue/PROVENANCE.md. Same
# gitignored-but-baked-into-image convention as roms/smoothtalker/engine.bin.
_BIN_DIR = Path(__file__).resolve().parent.parent / "roms" / "monologue" / "bin"

_OUT_RATE = core.OUT_RATE


class MonologueEngine(BaseTTSEngine):
    """First Byte Monologue / ProVoice (Windows 3.1 era). Runs the genuine
    16-bit engine under a Win16-on-Unicorn emulator - see
    providers/_monologue_engine/core.py for the emulation details."""

    def get_voices(self) -> List[str]:
        return list(core.VOICES.keys())

    def is_available(self) -> bool:
        return _BIN_DIR.is_dir() and (_BIN_DIR / "FB_SPCH.DLL").exists()

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            return await asyncio.to_thread(self._synthesize_sync, text, voice, output_path)
        except Exception:
            return False

    def _synthesize_sync(self, text: str, voice: str, output_path: Path) -> bool:
        text = (text or "").strip()
        if not text:
            return False

        # A fresh Engine/emulator per request rather than a shared resident
        # instance: Unicorn contexts aren't safe to share across concurrent
        # requests, and booting one (module load + WinMain init) is cheap
        # (tens of ms) next to the engine's own synthesis time.
        engine = core.Engine(str(_BIN_DIR))
        if voice and voice in core.VOICES:
            engine.set_voice(voice)

        pcm16 = bytearray()
        engine.speak(text, on_block=pcm16.extend)

        if not pcm16:
            return False

        return encode_pcm_to_mp3(bytes(pcm16), _OUT_RATE, 1, output_path)
