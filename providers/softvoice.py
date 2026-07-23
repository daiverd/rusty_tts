"""
SoftVoice, Inc. TTS Engine (TIBASE32.DLL)

Runs the real TIBASE32.DLL + TIENG32.DLL (SoftVoice, Inc.'s "Base DLL",
originally shipped in Microsoft Plus! for Kids' "Talk It!" - the same
company behind SAM) through a small Unicorn-CPU-emulated Win32 shim
(native/softvoice/sv_shim.c) instead of Wine, same approach as
providers/keynote.py. The DLL's ~35 Win32 imports (KERNEL32 memory/module
calls, a from-scratch fake Win32 message queue for its own internal window,
and WINMM waveOut*/timeSetEvent - captured/driven by us rather than played
on a real device) are serviced by hand-written C stubs.

Unlike BestSpeech, TIBASE32.DLL is genuinely asynchronous: SVTTS() kicks off
synthesis and returns almost immediately, streaming audio via double-
buffered waveOutWrite calls driven by its own timeSetEvent timer callback
and completion messages posted to its own internal window. sv_shim.c plays
the role of both the Win32 audio subsystem (capturing waveOutWrite instead
of any real playback) and the host application's message loop (which a real
embedding app like NVDA provides for free - we don't have one, so the shim
drains its own fake message queue and pumps the timer callback directly
until the DLL posts its "speech done" notification).

Only English (TIENG32.DLL) is wired up; TISPAN32.DLL (Spanish) is present
in roms/softvoice/ but not yet reachable - the DLL loads its language
module via a hardcoded LoadLibraryA("tieng32.dll"), with a separate
SVSetLanguage() call apparently needed to switch, not yet investigated.
"""

import ctypes
import logging
import threading
from ctypes import (
    CDLL, CFUNCTYPE, POINTER, c_char_p, c_int16, c_int, c_size_t, c_void_p,
)
from pathlib import Path
from typing import List

from . import BaseTTSEngine
from .mp3_encoder import encode_pcm_to_mp3

logger = logging.getLogger(__name__)

_LIB_PATH = Path("/usr/local/lib/libsv_shim.so")
_ROMS_DIR = Path(__file__).resolve().parent.parent / "roms" / "softvoice"
_BASE_DLL = _ROMS_DIR / "TIBASE32.DLL"
_ENG_DLL = _ROMS_DIR / "TIENG32.DLL"

_SAMPLE_RATE = 11025
_ENGLISH = 1  # SVOpenSpeech's "voice" arg is actually a language selector

# SVSetPersonality variant IDs (see sv.py's `variants` table from the NVDA
# softvoice2024 add-on - native/softvoice/sv_shim.h has the same list).
_VOICES = [
    "Male", "Female", "Large Male", "Child", "Giant Male", "Mellow Female",
    "Mellow Male", "Crisp Male", "The Fly", "Robotoid", "Martian",
    "Colossus", "Fast Fred", "Old Woman", "Munchkin", "Troll", "Nerd",
    "Milktoast", "Tipsy", "Choirboy",
]
_VOICE_INDEX = {name: i for i, name in enumerate(_VOICES)}

_SAMPLE_CB = CFUNCTYPE(None, POINTER(c_int16), c_size_t, c_void_p)


def _load_lib():
    lib = CDLL(str(_LIB_PATH))
    lib.sv_create.argtypes = [c_char_p, c_char_p, c_char_p]
    lib.sv_create.restype = c_void_p
    lib.sv_destroy.argtypes = [c_void_p]
    lib.sv_destroy.restype = None
    lib.sv_open.argtypes = [c_void_p, c_int]
    lib.sv_open.restype = c_int
    lib.sv_set_personality.argtypes = [c_void_p, c_int]
    lib.sv_set_personality.restype = c_int
    lib.sv_speak.argtypes = [c_void_p, c_char_p, _SAMPLE_CB, c_void_p]
    lib.sv_speak.restype = c_int
    return lib


class SoftVoiceEngine(BaseTTSEngine):
    """SoftVoice, Inc. formant synthesizer, run via a Unicorn-emulated Win32
    shim (no Wine)."""

    def __init__(self, config=None):
        super().__init__(config)
        self._lib = None
        self._engine = None
        self._lock = threading.Lock()
        self._load_error = None

    def get_voices(self) -> List[str]:
        return list(_VOICES)

    def _ensure_engine(self):
        if self._engine is not None:
            return True
        with self._lock:
            if self._engine is not None:
                return True
            try:
                if self._lib is None:
                    self._lib = _load_lib()
                engine = self._lib.sv_create(
                    str(_BASE_DLL).encode(), str(_ENG_DLL).encode(), b"tieng"
                )
                if not engine:
                    self._load_error = "sv_create returned NULL"
                    return False
                if self._lib.sv_open(engine, _ENGLISH) != 0:
                    self._load_error = "sv_open failed"
                    self._lib.sv_destroy(engine)
                    return False
                self._engine = engine
                return True
            except Exception as e:
                self._load_error = str(e)
                logger.error(f"SoftVoice engine init failed: {e}")
                return False

    def is_available(self) -> bool:
        if not _LIB_PATH.exists() or not _BASE_DLL.exists() or not _ENG_DLL.exists():
            return False
        return self._ensure_engine()

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        import asyncio

        try:
            return await asyncio.to_thread(self._synthesize_sync, text, voice, output_path)
        except Exception as e:
            logger.error(f"SoftVoice synthesis error: {e}")
            return False

    def _synthesize_sync(self, text: str, voice: str, output_path: Path) -> bool:
        if not self._ensure_engine():
            return False

        variant = _VOICE_INDEX.get(voice, 0)
        payload = text.encode("cp1252", "replace")

        pcm = bytearray()

        @_SAMPLE_CB
        def on_samples(samples, count, ctx):
            pcm.extend(ctypes.string_at(samples, count * 2))

        with self._lock:
            # Not reentrant per engine - SVSetPersonality/SVTTS share the one
            # open handle, and sv_speak drives the DLL's own timer/message
            # pump synchronously on this thread.
            self._lib.sv_set_personality(self._engine, variant)
            rc = self._lib.sv_speak(self._engine, payload, on_samples, None)

        if rc != 0 or not pcm:
            return False

        return encode_pcm_to_mp3(bytes(pcm), _SAMPLE_RATE, 1, output_path)
