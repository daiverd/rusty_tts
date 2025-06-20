from abc import ABC, abstractmethod
from typing import Dict, List
from dataclasses import dataclass
from pathlib import Path
import subprocess

@dataclass
class TTSProvider:
    """Configuration for a TTS provider"""
    name: str
    voices: List[str]
    enabled: bool = True
    config: Dict = None

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


def get_adaptive_mp3_settings(input_format: str = "wav") -> List[str]:
    """
    Get adaptive MP3 encoding settings that let FFmpeg analyze and optimize based on input
    
    Args:
        input_format: Input audio format
    
    Returns:
        List of FFmpeg arguments for adaptive MP3 encoding
    """
    return [
        "-acodec", "mp3",
        "-q:a", "2",           # Variable bitrate, high quality (0=best, 9=worst)
        "-compression_level", "2",  # Best compression efficiency
        "-joint_stereo", "1",  # Enable joint stereo for stereo inputs (ignored for mono)
        "-ac", "1",            # Force mono output (TTS is typically mono)
        # Let FFmpeg choose optimal sample rate based on input content
        # No explicit -ar flag means FFmpeg will analyze and choose the best rate
    ]


def run_tts_pipeline(tts_cmd: List[str], output_path: Path, input_format: str = "wav", engine_name: str = "unknown") -> bool:
    """
    Run TTS command and pipe output through FFmpeg to create MP3
    
    Args:
        tts_cmd: Command to run TTS engine
        output_path: Path where MP3 file should be saved
        input_format: Audio format from TTS engine (default: wav)
        engine_name: Name of TTS engine (unused - kept for compatibility)
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Get adaptive settings that let FFmpeg analyze the input
        mp3_settings = get_adaptive_mp3_settings(input_format)
        
        ffmpeg_cmd = [
            "ffmpeg",
            "-f", input_format,
            "-i", "pipe:0",
            *mp3_settings,
            str(output_path),
            "-y"
        ]
        
        # Create processes with pipes
        tts_process = subprocess.Popen(
            tts_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        ffmpeg_process = subprocess.Popen(
            ffmpeg_cmd,
            stdin=tts_process.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Close TTS stdout in parent to allow proper cleanup
        tts_process.stdout.close()
        
        # Wait for both processes to complete
        ffmpeg_output, ffmpeg_error = ffmpeg_process.communicate()
        tts_process.wait()
        
        return ffmpeg_process.returncode == 0 and output_path.exists()
        
    except Exception:
        return False


def run_tts_pipeline_with_stdin(tts_cmd: List[str], stdin_data: str, output_path: Path, input_format: str = "wav", engine_name: str = "unknown") -> bool:
    """
    Run TTS command with stdin input and pipe output through FFmpeg to create MP3
    
    Args:
        tts_cmd: Command to run TTS engine
        stdin_data: Data to send to TTS engine via stdin
        output_path: Path where MP3 file should be saved
        input_format: Audio format from TTS engine (default: wav)
        engine_name: Name of TTS engine (unused - kept for compatibility)
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Get adaptive settings that let FFmpeg analyze the input
        mp3_settings = get_adaptive_mp3_settings(input_format)
        
        ffmpeg_cmd = [
            "ffmpeg",
            "-f", input_format,
            "-i", "pipe:0",
            *mp3_settings,
            str(output_path),
            "-y"
        ]
        
        # Create processes with pipes
        tts_process = subprocess.Popen(
            tts_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        ffmpeg_process = subprocess.Popen(
            ffmpeg_cmd,
            stdin=tts_process.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Send data to TTS and close stdin
        tts_process.stdin.write(stdin_data)
        tts_process.stdin.close()
        tts_process.stdout.close()
        
        # Wait for completion
        ffmpeg_output, ffmpeg_error = ffmpeg_process.communicate()
        tts_process.wait()
        
        return ffmpeg_process.returncode == 0 and output_path.exists()
        
    except Exception:
        return False

# Import all engine implementations
from .pollinations import PollinationsEngine
from .espeak import EspeakEngine
from .festival import FestivalEngine
from .flite import FliteEngine
from .dectalk import DECtalkEngine
from .lpc import LPCEngine
from .sam import SAMEngine
from .coqui import CoquiTTSEngine

__all__ = [
    'TTSProvider',
    'BaseTTSEngine',
    'PollinationsEngine',
    'EspeakEngine',
    'FestivalEngine',
    'FliteEngine',
    'DECtalkEngine',
    'LPCEngine',
    'SAMEngine',
    'CoquiTTSEngine',
]