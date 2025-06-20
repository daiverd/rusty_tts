import subprocess
from pathlib import Path
from typing import List
from . import BaseTTSEngine

class LPCEngine(BaseTTSEngine):
    """FFmpeg-based LPC-style effect engine"""
    
    def get_voices(self) -> List[str]:
        return [
            "robot_low",      # Heavy LPC-style processing
            "robot_medium",   # Medium LPC-style processing  
            "robot_high",     # Light LPC-style processing
            "speak_spell",    # Speak & Spell emulation
            "vocoder"         # Vocoder-style effect
        ]
    
    def is_available(self) -> bool:
        try:
            import shutil
            return shutil.which("ffmpeg") is not None
        except Exception:
            return False
    
    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            # Use espeak to generate base audio, then process with FFmpeg
            wav_temp = output_path.with_suffix('_temp.wav')
            
            # Generate base audio with espeak
            espeak_cmd = [
                "espeak", "-s", "120", "-v", "en",
                "-w", str(wav_temp), text
            ]
            
            result = subprocess.run(espeak_cmd, capture_output=True)
            if result.returncode != 0:
                return False
            
            # Apply LPC-style effects with FFmpeg using adaptive settings
            effect_filters = self._get_lpc_filter(voice)
            
            from . import get_adaptive_mp3_settings
            mp3_settings = get_adaptive_mp3_settings("wav")
            
            ffmpeg_cmd = [
                "ffmpeg",
                "-i", str(wav_temp),
                "-af", effect_filters,
                *mp3_settings,
                str(output_path), "-y"
            ]
            
            result = subprocess.run(ffmpeg_cmd, capture_output=True)
            wav_temp.unlink(missing_ok=True)
            
            return result.returncode == 0 and output_path.exists()
            
        except Exception:
            return False
    
    def _get_lpc_filter(self, voice: str) -> str:
        """Generate FFmpeg filter chain for LPC-like effects"""
        
        if voice == "robot_low":
            # Heavy robot effect using bitcrush + formant filtering
            return (
                "aformat=sample_fmts=s16:sample_rates=8000,"  # Downsample
                "bitplanar=0.125,"                            # Bit reduction
                "highpass=f=300,"                             # Remove low freq
                "lowpass=f=3000,"                             # Remove high freq
                "tremolo=f=8:d=0.4,"                          # Add tremolo
                "aformat=sample_rates=22050"                  # Upsample
            )
            
        elif voice == "robot_medium":
            # Medium robot effect
            return (
                "aformat=sample_rates=11025,"
                "bitplanar=0.25,"
                "highpass=f=200,"
                "lowpass=f=4000,"
                "vibrato=f=6:d=0.3"
            )
            
        elif voice == "speak_spell":
            # Speak & Spell emulation
            return (
                "aformat=sample_fmts=s16:sample_rates=8000,"  # Low sample rate
                "bitplanar=0.2,"                              # Bit crush
                "dynaudnorm=p=0.95,"                          # Normalize
                "highpass=f=500,"                             # Formant shaping
                "lowpass=f=2500,"
                "tremolo=f=25:d=0.1,"                         # Slight flutter
                "volume=0.8"
            )
            
        elif voice == "vocoder":
            # Vocoder-style effect using multiple bandpass filters
            return (
                "asplit=8[a0][a1][a2][a3][a4][a5][a6][a7];"
                "[a0]bandpass=f=200:w=100[b0];"
                "[a1]bandpass=f=400:w=100[b1];"
                "[a2]bandpass=f=800:w=200[b2];"
                "[a3]bandpass=f=1600:w=200[b3];"
                "[a4]bandpass=f=3200:w=400[b4];"
                "[a5]bandpass=f=6400:w=400[b5];"
                "[a6]bandpass=f=12800:w=800[b6];"
                "[a7]bandpass=f=25600:w=1600[b7];"
                "[b0][b1][b2][b3][b4][b5][b6][b7]amix=inputs=8"
            )
            
        else:  # robot_high or default
            return (
                "aformat=sample_rates=16000,"
                "bitplanar=0.5,"
                "dynaudnorm=p=0.9"
            )