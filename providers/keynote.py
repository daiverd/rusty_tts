"""
BestSpeech / Keynote Gold TTS Engine

Runs the real b32_tts.dll (a 32-bit Windows PE build of the 1985/1991
Berkeley Speech Technologies "BestSpeech" formant synthesizer, surfaced by
rommix0 as "Keynote Gold") through a small Unicorn-CPU-emulated Win32 shim
(native/keynote/bst_shim.c, vendored from cullen-gallagher/BestSpeechForMac)
instead of Wine - the DLL's ~56 imports (memory/TLS/critical-section
KERNEL32 calls, a no-op USER32 message window, and waveOut* which is
captured rather than played) are serviced by hand-written C stubs, so
there's no Windows/Wine dependency, no subprocess spawn, no per-request
DLL-load cost. Runs in-process, same shape as providers/smoothtalker.py.
"""

import ctypes
import logging
import threading
from ctypes import (
    CDLL, CFUNCTYPE, POINTER, byref,
    c_char_p, c_int16, c_size_t, c_void_p,
)
from pathlib import Path
from typing import List

from . import BaseTTSEngine
from .mp3_encoder import encode_pcm_to_mp3

logger = logging.getLogger(__name__)

_LIB_PATH = Path("/usr/local/lib/libbst_shim.so")
_DLL_PATH = Path(__file__).resolve().parent.parent / "roms" / "keynote" / "b32_tts.dll"

_SAMPLE_RATE = 11025

# The engine's built-in voices: (name, identity prefix, rate prefix). Both
# prefixes are the inline `~cmd]` command sequences bst_wrapper.cpp (see
# @rommix0's BST.h) uses to select each named voice; bst_shim.h only
# exposes the identity half via bst_voice_prefix(), so the rate half is
# reproduced here to keep every voice's authentic sound (native/keynote/
# bst_shim.c's g_voice_data table has the same values).
_VOICES = [
    ("Fred",    "~v0]~e3]~h0]~u0]~f80]",     "~r0]"),
    ("Sara",    "~v2]~e3]~h-20]~u0]~f175]",  "~r0]"),
    ("Hary",    "~v3]~e3]~h10]~u0]~f65]",    "~r5]"),
    ("Wendy",   "~v2]~e1]~h50]~u0]~f150]",   "~r-5]"),
    ("Dexter",  "~v6]~e6]~h0]~u-25]~f90]",   "~r7]"),
    ("Alien",   "~v4]~e6]~h-50]~u-20]~f115]", "~r-20]"),
    ("Kit",     "~v5]~e3]~h40]~u0]~f230]",   "~r-10]"),
    ("Bruno",   "~v3]~e3]~h50]~u0]~f60]",    "~r8]"),
    ("Ghost",   "~v3]~e2]~h50]~u0]~f60]",    "~r8]"),
    ("Peeper",  "~v2]~e2]~h0]~u5]~f80]",     "~r0]"),
    ("Dracula", "~v3]~e3]~h45]~u-5]~f47]",   "~r10]"),
    ("Granny",  "~v4]~e3]~h-60]~u0]~f350]",  "~r20]"),
    ("Martha",  "~v6]~e4]~h100]~u-5]~f300]", "~r-10]"),
    ("Tim",     "~v3]~e4]~h-10]~u0]~f60]",   "~r-10]"),
]
_VOICE_PREFIX = {name: ident + rate for name, ident, rate in _VOICES}

_SAMPLE_CB = CFUNCTYPE(None, POINTER(c_int16), c_size_t, c_void_p)


def _load_lib():
    lib = CDLL(str(_LIB_PATH))
    lib.bst_create.argtypes = [c_char_p]
    lib.bst_create.restype = c_void_p
    lib.bst_destroy.argtypes = [c_void_p]
    lib.bst_destroy.restype = None
    lib.bst_speak.argtypes = [c_void_p, c_char_p, _SAMPLE_CB, c_void_p]
    lib.bst_speak.restype = ctypes.c_int
    return lib


class BestSpeechEngine(BaseTTSEngine):
    """BestSpeech / Keynote Gold formant synthesizer, run via a Unicorn-
    emulated Win32 shim (no Wine)."""

    def __init__(self, config=None):
        super().__init__(config)
        self._lib = None
        self._engine = None
        self._lock = threading.Lock()
        self._load_error = None

    def get_voices(self) -> List[str]:
        return [name for name, _, _ in _VOICES]

    def _ensure_engine(self):
        if self._engine is not None:
            return True
        with self._lock:
            if self._engine is not None:
                return True
            try:
                if self._lib is None:
                    self._lib = _load_lib()
                engine = self._lib.bst_create(str(_DLL_PATH).encode())
                if not engine:
                    self._load_error = "bst_create returned NULL"
                    return False
                self._engine = engine
                return True
            except Exception as e:
                self._load_error = str(e)
                logger.error(f"BestSpeech engine init failed: {e}")
                return False

    def is_available(self) -> bool:
        if not _LIB_PATH.exists() or not _DLL_PATH.exists():
            return False
        return self._ensure_engine()

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        import asyncio

        try:
            return await asyncio.to_thread(self._synthesize_sync, text, voice, output_path)
        except Exception as e:
            logger.error(f"BestSpeech synthesis error: {e}")
            return False

    def _synthesize_sync(self, text: str, voice: str, output_path: Path) -> bool:
        if not self._ensure_engine():
            return False

        prefix = _VOICE_PREFIX.get(voice, "")
        payload = (prefix + text).encode("cp1252", "replace")

        pcm = bytearray()

        @_SAMPLE_CB
        def on_samples(samples, count, ctx):
            pcm.extend(ctypes.string_at(samples, count * 2))

        with self._lock:
            # bst_speak is not reentrant per engine (see bst_shim.h) - the
            # lock also guards against a request landing mid bst_create()
            # from another thread on first use.
            rc = self._lib.bst_speak(self._engine, payload, on_samples, None)

        if rc != 0 or not pcm:
            return False

        return encode_pcm_to_mp3(bytes(pcm), _SAMPLE_RATE, 1, output_path)
