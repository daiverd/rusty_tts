"""
Apple Eloquence TTS Engine

Runs Apple's bundled ETI Eloquence 6.1 engine (VoiceOver's TTS backend on
macOS/iOS/tvOS) - converted from Mach-O to native Linux ELF .so files by
~/src/speech/Apple-Eloquence-ELF's macho2elf tool (see
roms/eloquence/PROVENANCE.md).

Each language talks to its own small resident helper process
(native/eloquence/host.c, built to /usr/local/bin/eloquence_host) over a
framed stdin/stdout protocol, rather than dlopen'ing eci.so directly via
ctypes in this process, for two reasons discovered empirically:

1. The converted .so's pin their sections at their original Mach-O
   virtual addresses. eciNew() reliably returns NULL when that fixed
   range collides with something else already mapped in the process -
   which happens close to 100% of the time in a real FastAPI process
   with numpy/nltk/etc. already loaded, but essentially never in a small
   dedicated process with nothing else going on.
2. eciNew() only succeeds when the process's working directory was set
   *before* the process started (e.g. via subprocess.Popen(cwd=...)) -
   calling os.chdir() at runtime inside an already-running process to
   reach the exact same directory reliably fails instead. So each
   language needs its own process, started with cwd already pointed at
   that language's eci.ini directory - a single resident process cannot
   loop over multiple languages via internal chdir().

See host.c's header comment for the full story.
"""

import asyncio
import logging
import subprocess
import struct
import threading
from pathlib import Path
from typing import List

from . import BaseTTSEngine
from .mp3_encoder import encode_pcm_to_mp3

logger = logging.getLogger(__name__)

_HOST_BIN = Path("/usr/local/bin/eloquence_host")
_ROMS_DIR = Path(__file__).resolve().parent.parent / "roms" / "eloquence"
_ECI_SO = _ROMS_DIR / "eci.so"
_LANGDIRS = _ROMS_DIR / "langdirs"

_SAMPLE_RATE = 11025  # Apple's build only accepts eciSampleRate 0 (8kHz) or 1 (11025Hz)

_VOICES = {
    "en-US": "enu", "en-GB": "eng", "de-DE": "deu", "fr-FR": "fra",
    "fr-CA": "frc", "es-ES": "esp", "es-MX": "esm", "it-IT": "ita",
    "fi-FI": "fin", "pt-BR": "ptb",
}

_MAX_SPAWN_ATTEMPTS = 5


def _read_exact(f, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = f.read(n - len(buf))
        if not chunk:
            raise EOFError(f"eloquence_host closed connection (wanted {n} bytes, got {len(buf)})")
        buf += chunk
    return buf


class EloquenceEngine(BaseTTSEngine):
    """Apple ETI Eloquence 6.1, run as native Linux ELF via one resident
    subprocess per language (see module docstring for why)."""

    def __init__(self, config=None):
        super().__init__(config)
        self._procs = {}
        self._locks = {voice: threading.Lock() for voice in _VOICES}

    def get_voices(self) -> List[str]:
        return list(_VOICES.keys())

    def is_available(self) -> bool:
        return _HOST_BIN.exists() and _ECI_SO.exists() and _LANGDIRS.exists()

    def _spawn(self, voice: str):
        lang = _VOICES[voice]
        langdir = _LANGDIRS / lang
        for attempt in range(1, _MAX_SPAWN_ATTEMPTS + 1):
            proc = subprocess.Popen(
                [str(_HOST_BIN), str(_ECI_SO)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=str(langdir),
            )
            line = proc.stdout.readline()
            if line.strip() == b"READY":
                return proc
            proc.stderr.close()
            proc.stdout.close()
            proc.stdin.close()
            proc.wait(timeout=5)
            logger.warning(
                f"eloquence_host ({voice}) failed to start "
                f"(attempt {attempt}/{_MAX_SPAWN_ATTEMPTS}): {line!r}"
            )
        logger.error(f"eloquence_host ({voice}) failed to start after {_MAX_SPAWN_ATTEMPTS} attempts")
        return None

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            return await asyncio.to_thread(self._synthesize_sync, text, voice, output_path)
        except Exception as e:
            logger.error(f"Eloquence synthesis error: {e}")
            return False

    def _synthesize_sync(self, text: str, voice: str, output_path: Path) -> bool:
        if voice not in _VOICES:
            return False
        text_bytes = text.encode("latin-1", "replace")
        lock = self._locks[voice]

        with lock:
            proc = self._procs.get(voice)
            if proc is None or proc.poll() is not None:
                proc = self._spawn(voice)
                self._procs[voice] = proc
            if proc is None:
                return False

            try:
                proc.stdin.write(struct.pack("<i", len(text_bytes)))
                proc.stdin.write(text_bytes)
                proc.stdin.flush()
                status, = struct.unpack("<i", _read_exact(proc.stdout, 4))
                pcm_len, = struct.unpack("<i", _read_exact(proc.stdout, 4))
                pcm = _read_exact(proc.stdout, pcm_len) if pcm_len else b""
            except (BrokenPipeError, EOFError, OSError) as e:
                logger.error(f"eloquence_host ({voice}) connection lost: {e}")
                self._procs[voice] = None
                return False

        if status != 0 or not pcm:
            return False

        return encode_pcm_to_mp3(pcm, _SAMPLE_RATE, 1, output_path)
