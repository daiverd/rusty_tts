import subprocess
from pathlib import Path
from typing import List
from . import BaseTTSEngine

class SAMEngine(BaseTTSEngine):
    """SAM (Software Automatic Mouth) - Classic 1982 C64 TTS"""
    
    def get_voices(self) -> List[str]:
        # SAM voice presets with speed/pitch/throat/mouth parameters
        return [
            "sam",           # Default SAM voice (72,64,128,128)
            "elf",           # Elf (72,64,110,160)
            "robot",  # Little Robot (92,60,190,190)
            "stuffy",    # Stuffy Guy (82,72,110,105)
            "old", # Little Old Lady (82,32,145,145)
            "alien" # Extra-Terrestrial (100,64,150,200)
        ]
    
    def is_available(self) -> bool:
        try:
            import shutil
            return (shutil.which("sam") is not None and 
                    shutil.which("ffmpeg") is not None)
        except Exception:
            return False
    
    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            # Voice parameter mappings
            voice_params = {
                "sam": ["-speed", "72", "-pitch", "64", "-throat", "128", "-mouth", "128"],
                "elf": ["-speed", "72", "-pitch", "64", "-throat", "110", "-mouth", "160"],
                "robot": ["-speed", "92", "-pitch", "60", "-throat", "190", "-mouth", "190"],
                "stuffy": ["-speed", "82", "-pitch", "72", "-throat", "110", "-mouth", "105"],
                "old": ["-speed", "82", "-pitch", "32", "-throat", "145", "-mouth", "145"],
                "alien": ["-speed", "100", "-pitch", "64", "-throat", "150", "-mouth", "200"]
            }
            
            params = voice_params.get(voice, voice_params["sam"])
            
            # SAM command to output WAV to stdout
            sam_cmd = [
                "sam",
                *params,
                "-wav", "/dev/stdout",  # Output WAV to stdout
                text
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
            sam_process = subprocess.Popen(
                sam_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=sam_process.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            sam_process.stdout.close()
            
            ffmpeg_output, ffmpeg_error = ffmpeg_process.communicate()
            sam_process.wait()
            
            return ffmpeg_process.returncode == 0 and output_path.exists()
            
        except Exception:
            return False