from abc import ABC, abstractmethod
from typing import Dict, List
from dataclasses import dataclass, field
from pathlib import Path
import subprocess

from .mp3_encoder import encode_pcm_to_mp3, encode_wav_to_mp3

@dataclass
class TTSProvider:
    """Configuration for a TTS provider"""
    name: str
    voices: List[str]
    enabled: bool = True
    config: Dict = field(default_factory=dict)

class BaseTTSEngine(ABC):
    """Abstract base class for TTS engines"""
    
    def __init__(self, config: Dict = None):
        self.config = config or {}
    
    @abstractmethod
    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        """Synthesize text to speech and save to output_path"""
        pass
    
    @abstractmethod
    def get_voices(self) -> List[str]:
        """Get list of available voices"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the engine is available/installed"""
        pass


def run_tts_pipeline(tts_cmd: List[str], output_path: Path, input_format: str = "wav") -> bool:
    """
    Run a TTS command that writes a WAV file to stdout, and encode it to MP3
    in-process (no ffmpeg subprocess - see mp3_encoder.py).

    Args:
        tts_cmd: Command to run TTS engine
        output_path: Path where MP3 file should be saved
        input_format: Audio format from TTS engine (only "wav" is supported)

    Returns:
        True if successful, False otherwise
    """
    try:
        tts_process = subprocess.run(tts_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if not tts_process.stdout:
            return False

        return encode_wav_to_mp3(tts_process.stdout, output_path)

    except Exception:
        return False


def run_tts_pipeline_with_stdin(tts_cmd: List[str], stdin_data: str, output_path: Path, input_format: str = "wav") -> bool:
    """
    Run a TTS command that reads text from stdin and writes a WAV file to
    stdout, and encode it to MP3 in-process (no ffmpeg subprocess).

    Args:
        tts_cmd: Command to run TTS engine
        stdin_data: Data to send to TTS engine via stdin
        output_path: Path where MP3 file should be saved
        input_format: Audio format from TTS engine (only "wav" is supported)

    Returns:
        True if successful, False otherwise
    """
    try:
        tts_process = subprocess.run(
            tts_cmd,
            input=stdin_data.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        if not tts_process.stdout:
            return False

        return encode_wav_to_mp3(tts_process.stdout, output_path)

    except Exception:
        return False


def run_tts_pipeline_raw(tts_cmd: List[str], output_path: Path,
                          sample_rate: int, channels: int = 1) -> bool:
    """
    Run a TTS command that writes raw PCM (s16le) to stdout, and encode it
    to MP3 in-process. Needed by engines (like DECtalk) whose output has no
    self-describing container, so the sample rate/channels must be passed
    explicitly instead of read off a WAV header.

    Args:
        tts_cmd: Command to run TTS engine
        output_path: Path where MP3 file should be saved
        sample_rate: Sample rate of the raw PCM the tts_cmd emits
        channels: Channel count of the raw PCM the tts_cmd emits

    Returns:
        True if successful, False otherwise
    """
    try:
        tts_process = subprocess.run(tts_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if not tts_process.stdout:
            return False

        return encode_pcm_to_mp3(tts_process.stdout, sample_rate, channels, output_path)

    except Exception:
        return False


def run_tts_pipeline_stdin_raw(tts_cmd: List[str], stdin_data: bytes, output_path: Path,
                                sample_rate: int, channels: int = 1) -> bool:
    """
    Run a TTS command that reads a raw byte stream from stdin and writes raw
    PCM (s16le) to stdout, and encode it to MP3 in-process.

    This is the combination `run_tts_pipeline_with_stdin` and
    `run_tts_pipeline_raw` don't cover: stdin input (like allophone codes or
    LPC frame bytes, not text) *and* raw PCM output with explicit sample
    rate/channels, needed by the retrochip speech-chip emulator CLI.

    Args:
        tts_cmd: Command to run TTS engine
        stdin_data: Raw bytes to send to TTS engine via stdin (e.g. allophone
            codes or LPC frame bytes, not text)
        output_path: Path where MP3 file should be saved
        sample_rate: Sample rate of the raw PCM the tts_cmd emits
        channels: Channel count of the raw PCM the tts_cmd emits

    Returns:
        True if successful, False otherwise
    """
    try:
        tts_process = subprocess.run(
            tts_cmd,
            input=stdin_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        if not tts_process.stdout:
            return False

        # Chip-emulator/LPC-frame output loudness varies a lot depending on
        # the source voice's own gain analysis (an upstream LPC encoder's
        # relative gain normalization can land much quieter for some source
        # voices than others) - normalize so every voice on this path is
        # audible.
        return encode_pcm_to_mp3(tts_process.stdout, sample_rate, channels, output_path, normalize=True)

    except Exception:
        return False


# Import all engine implementations
from .espeak import EspeakEngine
from .festival import FestivalEngine
from .flite import FliteEngine
from .dectalk import DECtalkEngine
from .sam import SAMEngine
from .piper import PiperEngine
from .coqui import CoquiTTSEngine
from .windows import WindowsEngine
from .tms5220 import Tms5220Engine
from .sp0256 import Sp0256Engine
from .votrax import VotraxEngine
from .textalker import TextalkerEngine
from .votrax_tnt import VotraxTypeNTalkEngine
from .votrax_pss import VotraxPersonalSpeechSystemEngine
from .snspell import SnSpellEngine
from .s14001a_calculator import S14001aCalculatorEngine
from .doubletalk import DoubleTalkEngine
from .smoothtalker import SmoothTalkerEngine
from .keynote import BestSpeechEngine
from .keynote_lang import BestSpeechLangEngine

__all__ = [
    'TTSProvider',
    'BaseTTSEngine',
    'EspeakEngine',
    'FestivalEngine',
    'FliteEngine',
    'DECtalkEngine',
    'SAMEngine',
    'PiperEngine',
    'CoquiTTSEngine',
    'WindowsEngine',
    'Tms5220Engine',
    'Sp0256Engine',
    'VotraxEngine',
    'TextalkerEngine',
    'VotraxTypeNTalkEngine',
    'VotraxPersonalSpeechSystemEngine',
    'SnSpellEngine',
    'S14001aCalculatorEngine',
    'DoubleTalkEngine',
    'SmoothTalkerEngine',
    'BestSpeechEngine',
    'BestSpeechLangEngine',
]