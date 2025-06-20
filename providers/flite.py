import subprocess
from pathlib import Path
from typing import List
from . import BaseTTSEngine

class FliteEngine(BaseTTSEngine):
    """Flite (Festival Lite) TTS Engine"""
    
    def get_voices(self) -> List[str]:
        # Common Flite voices - you can expand this based on what's installed
        return ["kal16", "kal", "awb", "rms", "slt"]
    
    def is_available(self) -> bool:
        try:
            subprocess.run(["flite", "-lv"], 
                         capture_output=True, check=True)
            subprocess.run(["ffmpeg", "-version"], 
                         capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    
    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            # Flite command to output WAV to stdout
            flite_cmd = [
                "flite",
                "-voice", voice,
                "-t", text,
                "-o", "/dev/stdout"  # Output to stdout
            ]
            
            # Get adaptive settings that let FFmpeg analyze the input
            from . import get_adaptive_mp3_settings
            mp3_settings = get_adaptive_mp3_settings("wav")
            
            ffmpeg_cmd = [
                "ffmpeg",
                "-f", "wav",
                "-i", "pipe:0",
                *mp3_settings,
                str(output_path),
                "-y"
            ]
            
            # Create processes with pipes
            flite_process = subprocess.Popen(
                flite_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=flite_process.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # Close flite stdout in parent
            flite_process.stdout.close()
            
            # Wait for both processes
            ffmpeg_output, ffmpeg_error = ffmpeg_process.communicate()
            flite_process.wait()
            
            return ffmpeg_process.returncode == 0 and output_path.exists()
            
        except Exception:
            return False