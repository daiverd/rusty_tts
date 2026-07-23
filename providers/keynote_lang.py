"""
BestSpeech multi-language TTS Engine

A second, later (2006) build of the same BestSpeech engine as
providers/keynote.py's b32_tts.dll, distributed as 13 separate per-language
DLLs (originally bundled with the Lingvosoft Talking Dictionary programs).
Uniform Init_TTS/Say_TTS/DeInit_TTS API, UTF-16 text in - a cleaner, simpler
surface than b32_tts.dll's (no USER32/window dependency at all). Run the
same way: Unicorn-emulated Win32 shim, no Wine, in-process (see
native/keynote/bst_lang_shim.c).
"""

import asyncio
import ctypes
import logging
import threading
from ctypes import CFUNCTYPE, POINTER, c_char_p, c_int16, c_size_t, c_uint16, c_void_p
from pathlib import Path
from typing import List

from . import BaseTTSEngine
from .mp3_encoder import encode_pcm_to_mp3

logger = logging.getLogger(__name__)

_LIB_PATH = Path("/usr/local/lib/libbst_lang_shim.so")
_DLL_DIR = Path(__file__).resolve().parent.parent / "roms" / "keynote" / "lang"

_SAMPLE_RATE = 11025

# Language code -> DLL filename. All 13 DLLs from the 2006 archive are
# included even where a plain-English voice already exists elsewhere in
# rusty_tts (dectalk, piper, etc.) - this specific engine build may behave
# differently, and duplicates are easy to prune later once compared.
_VOICES = {
    "ara": "dll_ara.dll",  # currently produces silent output - see PLAN notes
    "dut": "dll_dut.dll",
    "eng": "dll_eng.dll",
    "fre": "dll_fre.dll",
    "ger": "dll_ger.dll",
    "gre": "dll_gre.dll",
    "heb": "dll_heb.dll",
    "ita": "dll_ita.dll",
    "jpn": "dll_jpn.dll",
    "pol": "dll_pol.dll",
    "por": "dll_por.dll",
    "rus": "dll_rus.dll",
    "spa": "dll_spa.dll",
}

_SAMPLE_CB = CFUNCTYPE(None, POINTER(c_int16), c_size_t, c_void_p)


def _load_lib():
    lib = ctypes.CDLL(str(_LIB_PATH))
    lib.bstl_create.argtypes = [c_char_p]
    lib.bstl_create.restype = c_void_p
    lib.bstl_destroy.argtypes = [c_void_p]
    lib.bstl_destroy.restype = None
    lib.bstl_speak.argtypes = [c_void_p, POINTER(c_uint16), _SAMPLE_CB, c_void_p]
    lib.bstl_speak.restype = ctypes.c_int
    return lib


class BestSpeechLangEngine(BaseTTSEngine):
    """Multi-language BestSpeech engine (13 languages), run via the same
    Unicorn-emulated Win32 shim technique as providers/keynote.py, no Wine."""

    def __init__(self, config=None):
        super().__init__(config)
        self._lib = None
        self._engines = {}
        self._lock = threading.Lock()

    def get_voices(self) -> List[str]:
        return list(_VOICES.keys())

    def _ensure_lib(self) -> bool:
        if self._lib is not None:
            return True
        try:
            self._lib = _load_lib()
            return True
        except Exception as e:
            logger.error(f"BestSpeechLang library load failed: {e}")
            return False

    def _ensure_engine(self, voice: str):
        if voice in self._engines:
            return self._engines[voice]
        with self._lock:
            if voice in self._engines:
                return self._engines[voice]
            if not self._ensure_lib():
                return None
            dll_path = _DLL_DIR / _VOICES[voice]
            engine = self._lib.bstl_create(str(dll_path).encode())
            self._engines[voice] = engine if engine else None
            return self._engines[voice]

    def is_available(self) -> bool:
        if not _LIB_PATH.exists() or not _DLL_DIR.exists():
            return False
        # Cheap check only - creating all 13 engines eagerly isn't worth the
        # startup cost; each is created lazily on first use of that voice.
        return any((_DLL_DIR / fname).exists() for fname in _VOICES.values())

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            return await asyncio.to_thread(self._synthesize_sync, text, voice, output_path)
        except Exception as e:
            logger.error(f"BestSpeechLang synthesis error: {e}")
            return False

    def _synthesize_sync(self, text: str, voice: str, output_path: Path) -> bool:
        if voice not in _VOICES:
            return False
        engine = self._ensure_engine(voice)
        if not engine:
            return False

        text_utf16 = text.encode("utf-16-le") + b"\x00\x00"
        buf = ctypes.create_string_buffer(text_utf16, len(text_utf16))
        buf_p = ctypes.cast(buf, POINTER(c_uint16))

        pcm = bytearray()

        @_SAMPLE_CB
        def on_samples(samples, count, ctx):
            pcm.extend(ctypes.string_at(samples, count * 2))

        with self._lock:
            # bstl_speak is not reentrant per engine; each language has its
            # own engine instance, but the shared lock keeps concurrent
            # requests for different languages from racing on ctypes state.
            rc = self._lib.bstl_speak(engine, buf_p, on_samples, None)

        if rc != 0 or not pcm:
            return False

        return encode_pcm_to_mp3(bytes(pcm), _SAMPLE_RATE, 1, output_path)
