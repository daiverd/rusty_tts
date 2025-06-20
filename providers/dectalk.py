import subprocess
from pathlib import Path
from typing import List
from . import BaseTTSEngine, run_tts_pipeline

class DECtalkEngine(BaseTTSEngine):
    """DECtalk TTS Engine - The famous Stephen Hawking voice"""
    
    def get_voices(self) -> List[str]:
        # DECtalk speaker numbers (0-9)
        return [
            "0",  # Perfect Paul (default, Stephen Hawking's voice)
            "1",  # Beautiful Betty
            "2",  # Huge Harry
            "3",  # Frail Frank
            "4",  # Doctor Dennis
            "5",  # Kit the Kid
            "6",  # Uppity Ursula
            "7",  # Rough Rita
            "8",  # Whispering Wendy
            "9"   # Variable (user-defined)
        ]
    
    def is_available(self) -> bool:
        try:
            # Check if 'dectalk' binary exists (compiled as 'dectalk' in Docker)
            result = subprocess.run(["dectalk", "-a", '"hi"', "-fo", "stdout:raw"], 
                         capture_output=True, check=True)
            subprocess.run(["ffmpeg", "-version"], 
                         capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    
    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        # DECtalk 'dectalk' command to output raw PCM to stdout
        dectalk_cmd = [
            "dectalk",
            "-s", voice,                    # Speaker number (0-9)
            "-fo", "stdout:raw",            # Output raw PCM to stdout
            "-a", text                      # Text to speak
        ]
        
        # DECtalk outputs raw PCM, so we need a custom pipeline with adaptive settings
        try:
            from . import get_adaptive_mp3_settings
            mp3_settings = get_adaptive_mp3_settings("s16le")
            
            ffmpeg_cmd = [
                "ffmpeg",
                "-f", "s16le",                  # Raw PCM 16-bit little endian
                "-ar", "11025",                 # Sample rate (DECtalk default)
                "-ac", "1",                     # Mono
                "-i", "pipe:0",
                *mp3_settings,                  # Adaptive MP3 settings
                str(output_path),
                "-y"
            ]
            
            # Create processes with pipes
            dectalk_process = subprocess.Popen(
                dectalk_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=dectalk_process.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            dectalk_process.stdout.close()
            
            ffmpeg_output, ffmpeg_error = ffmpeg_process.communicate()
            dectalk_process.wait()
            
            return ffmpeg_process.returncode == 0 and output_path.exists()
            
        except Exception:
            return False