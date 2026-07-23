"""
WinTalker TTS Engine

Runs the classic WinTalker formant synthesizer (a Windows port of the
1990s Mac MacinTalk/PlainTalk voice family - 17 voices: Fred, Kathy,
Zarvox, etc.) via `lintalker` (github.com/dectalk/lintalker), an
already-complete native Linux CLI port - no Wine, no CPU emulation. See
~/src/speech/WinTalker/PLAN.md for how that was found and verified.

The `wintalker` CLI synthesizes a whole utterance into memory and writes
one complete WAV file per invocation (`-o path`), rather than exposing a
streaming/render-buffer API, so this provider shells out per request and
reads the resulting file back - same shape as providers/doubletalk.py.
"""

import asyncio
import os
import re
import tempfile
from pathlib import Path
from typing import List

from . import BaseTTSEngine
from .mp3_encoder import encode_wav_to_mp3

_WT_BIN = Path(os.environ.get("WINTALKER_BIN", "/usr/local/bin/wintalker"))

# Order and spelling match lintalker's src/main.c voiceNames[] table
# exactly (index 0 = Fred = default voice).
_VOICES = [
    "Fred", "Kathy", "Princess", "Junior", "Ralph", "Whisper", "Zarvox",
    "Trinoids", "Bubbles", "Boing", "Bells", "Hysterical", "Deranged",
    "GoodNews", "BadNews", "PipeOrgan", "Cellos",
]


def _sanitize(text: str) -> str:
    # The engine's front-end indexes tables by raw byte value and expects
    # 7-bit ASCII (same constraint the WinTalker NVDA driver works around);
    # non-ASCII input risks garbage output rather than a clean error.
    text = re.sub(r"[^\x20-\x7e]", " ", text).strip() or "hello"
    # main.c's arg parser treats a leading '-' as an unrecognized flag,
    # not text - a leading space sidesteps that without changing the
    # spoken result.
    if text.startswith("-"):
        text = " " + text
    return text


class WinTalkerEngine(BaseTTSEngine):
    """WinTalker formant synthesizer (MacinTalk/PlainTalk-family voices),
    run via the native `wintalker` CLI (lintalker port, no Wine)."""

    def get_voices(self) -> List[str]:
        return list(_VOICES)

    def is_available(self) -> bool:
        return _WT_BIN.exists()

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        if voice not in _VOICES:
            voice = _VOICES[0]

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                wav_path = Path(tmpdir) / "out.wav"
                proc = await asyncio.create_subprocess_exec(
                    str(_WT_BIN), "-v", voice, "-o", str(wav_path), _sanitize(text),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    await asyncio.wait_for(proc.communicate(), timeout=30.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    return False

                if not wav_path.exists():
                    return False

                return encode_wav_to_mp3(wav_path.read_bytes(), output_path)
        except Exception:
            return False
