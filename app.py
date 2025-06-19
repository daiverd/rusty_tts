from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
import requests
import urllib.parse
import hashlib
import subprocess
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Dict, List
from dataclasses import dataclass

app = FastAPI(title="Text-to-Speech API", description="Generate MP3 audio from text using multiple providers")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://tts.example.com",
        "http://localhost:3000",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8080"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Length", "Content-Range", "Accept-Ranges"]
)

# Create audio directory
AUDIO_DIR = Path("audio_files")
AUDIO_DIR.mkdir(exist_ok=True)

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

class PollinationsEngine(BaseTTSEngine):
    """Pollinations API TTS Engine"""
    
    def get_voices(self) -> List[str]:
        return ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
    
    def is_available(self) -> bool:
        return True  # API-based, always available
    
    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        encoded_text = urllib.parse.quote(text)
        url = f"https://text.pollinations.ai/{encoded_text}"
        params = {
            "model": "openai-audio",
            "voice": voice
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            
            if 'audio/mpeg' in response.headers.get('Content-Type', ''):
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                return True
            return False
        except requests.exceptions.RequestException:
            return False

class EspeakEngine(BaseTTSEngine):
    """eSpeak-ng TTS Engine"""
    
    def get_voices(self) -> List[str]:
        # These are common eSpeak voices, you can expand this
        return ["en", "en-us", "en-gb", "es", "fr", "de", "it"]
    
    def is_available(self) -> bool:
        try:
            subprocess.run(["espeak-ng", "--version"], 
                         capture_output=True, check=True)
            subprocess.run(["ffmpeg", "-version"], 
                         capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    
    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            # Pipe eSpeak output directly to ffmpeg
            espeak_cmd = [
                "espeak-ng", 
                "-v", voice,
                "-s", "150",  # Speed
                "--stdout",   # Output to stdout instead of file
                text
            ]
            
            ffmpeg_cmd = [
                "ffmpeg",
                "-f", "wav",           # Input format
                "-i", "pipe:0",        # Read from stdin
                "-acodec", "mp3",      # Output codec
                "-b:a", "128k",        # Bitrate
                str(output_path),
                "-y"                   # Overwrite output file
            ]
            
            # Create processes with pipes
            espeak_process = subprocess.Popen(
                espeak_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=espeak_process.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # Close espeak stdout in parent to allow proper cleanup
            espeak_process.stdout.close()
            
            # Wait for both processes to complete
            ffmpeg_output, ffmpeg_error = ffmpeg_process.communicate()
            espeak_process.wait()
            
            return ffmpeg_process.returncode == 0 and output_path.exists()
            
        except Exception as e:
            return False

class FestivalEngine(BaseTTSEngine):
    """Festival TTS Engine"""
    
    def get_voices(self) -> List[str]:
        return ["kal_diphone", "rab_diphone", "don_diphone", "rms_diphone"]
    
    def is_available(self) -> bool:
        try:
            subprocess.run(["festival", "--version"], 
                         capture_output=True, check=True)
            subprocess.run(["ffmpeg", "-version"], 
                         capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    
    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            # Create Festival script that outputs to stdout
            festival_script = f'''
(voice_{voice})
(utt.save.wave 
  (utt.synth (Utterance Text "{text}"))
  "/dev/stdout" 'wav)
'''
            
            festival_cmd = ["festival"]
            
            ffmpeg_cmd = [
                "ffmpeg",
                "-f", "wav",
                "-i", "pipe:0",
                "-acodec", "mp3",
                "-b:a", "128k",
                str(output_path),
                "-y"
            ]
            
            # Create processes with pipes
            festival_process = subprocess.Popen(
                festival_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=festival_process.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # Send script to Festival and close stdin
            festival_process.stdin.write(festival_script)
            festival_process.stdin.close()
            festival_process.stdout.close()
            
            # Wait for completion
            ffmpeg_output, ffmpeg_error = ffmpeg_process.communicate()
            festival_process.wait()
            
            return ffmpeg_process.returncode == 0 and output_path.exists()
            
        except Exception:
            return False

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
            
            ffmpeg_cmd = [
                "ffmpeg",
                "-f", "wav",
                "-i", "pipe:0",
                "-acodec", "mp3",
                "-b:a", "128k",
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
            # Check if 'say' binary exists
            result = subprocess.run(["say", "-a", '"hi"', "-fo", "stdout:raw"], 
                         capture_output=True, check=True)
            subprocess.run(["ffmpeg", "-version"], 
                         capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    
    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            # DECtalk 'say' command to output WAV to stdout
            say_cmd = [
                "say",
                "-s", voice,                    # Speaker number (0-9)
                "-fo", "stdout:raw",            # Output raw PCM to stdout
                "-a", text                      # Text to speak
            ]
            
            ffmpeg_cmd = [
                "ffmpeg",
                "-f", "s16le",                  # Raw PCM 16-bit little endian
                "-ar", "11025",                 # Sample rate (DECtalk default)
                "-ac", "1",                     # Mono
                "-i", "pipe:0",
                "-acodec", "mp3",
                "-b:a", "128k",
                str(output_path),
                "-y"
            ]
            
            # Create processes with pipes
            say_process = subprocess.Popen(
                say_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=say_process.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            say_process.stdout.close()
            
            ffmpeg_output, ffmpeg_error = ffmpeg_process.communicate()
            say_process.wait()
            
            return ffmpeg_process.returncode == 0 and output_path.exists()
            
        except Exception:
            return False

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
            
            # Apply LPC-style effects with FFmpeg
            effect_filters = self._get_lpc_filter(voice)
            
            ffmpeg_cmd = [
                "ffmpeg",
                "-i", str(wav_temp),
                "-af", effect_filters,
                "-acodec", "mp3", "-b:a", "128k",
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
            
            ffmpeg_cmd = [
                "ffmpeg",
                "-f", "wav",
                "-i", "pipe:0",
                "-acodec", "mp3",
                "-b:a", "128k",
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

class CoquiTTSEngine(BaseTTSEngine):
    """Coqui TTS Engine (assumes you have it installed)"""
    
    def get_voices(self) -> List[str]:
        # These would be your installed Coqui models
        return ["tts_models/en/ljspeech/tacotron2-DDC", 
                "tts_models/en/ljspeech/glow-tts"]
    
    def is_available(self) -> bool:
        try:
            subprocess.run(["tts", "--help"], 
                         capture_output=True, check=True)
            subprocess.run(["ffmpeg", "-version"], 
                         capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    
    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            # Coqui TTS can output to stdout with --pipe_out
            tts_cmd = [
                "tts",
                "--text", text,
                "--model_name", voice,
                "--pipe_out"  # Output WAV to stdout
            ]
            
            ffmpeg_cmd = [
                "ffmpeg",
                "-f", "wav",
                "-i", "pipe:0",
                "-acodec", "mp3",
                "-b:a", "128k",
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
            
            tts_process.stdout.close()
            
            ffmpeg_output, ffmpeg_error = ffmpeg_process.communicate()
            tts_process.wait()
            
            return ffmpeg_process.returncode == 0 and output_path.exists()
            
        except Exception:
            return False

class TTSManager:
    """Manages multiple TTS engines"""
    
    def __init__(self):
        self.engines: Dict[str, BaseTTSEngine] = {}
        self.providers: Dict[str, TTSProvider] = {}
        self._initialize_engines()
    
    def _initialize_engines(self):
        """Initialize all available TTS engines"""
        engines = {
            "pollinations": PollinationsEngine(),
            "espeak": EspeakEngine(),
            "festival": FestivalEngine(),
            "flite": FliteEngine(),
            "dectalk": DECtalkEngine(),
            "lpc": LPCEngine(),
            "sam": SAMEngine(),
            "coqui": CoquiTTSEngine(),
        }
        
        for name, engine in engines.items():
            if engine.is_available():
                self.engines[name] = engine
                self.providers[name] = TTSProvider(
                    name=name,
                    voices=engine.get_voices(),
                    enabled=True
                )
    
    def get_available_providers(self) -> Dict[str, TTSProvider]:
        """Get all available providers"""
        return {k: v for k, v in self.providers.items() if v.enabled}
    
    def get_provider_voices(self, provider: str) -> List[str]:
        """Get voices for a specific provider"""
        if provider in self.providers:
            return self.providers[provider].voices
        return []
    
    async def synthesize(self, text: str, provider: str, voice: str, output_path: Path) -> bool:
        """Synthesize text using specified provider"""
        if provider not in self.engines:
            return False
        
        if voice not in self.providers[provider].voices:
            return False
        
        return await self.engines[provider].synthesize(text, voice, output_path)

# Initialize TTS Manager
tts_manager = TTSManager()

def generate_filename(text: str, provider: str, voice: str) -> str:
    """Generate a unique filename based on text, provider, and voice"""
    content = f"{text}_{provider}_{voice}"
    hash_object = hashlib.md5(content.encode())
    return f"{hash_object.hexdigest()}.mp3"

async def create_audio_file(text: str, provider: str, voice: str) -> str:
    """Create audio file using specified provider"""
    filename = generate_filename(text, provider, voice)
    filepath = AUDIO_DIR / filename
    
    # If file already exists, return the filename
    if filepath.exists():
        return filename
    
    # Generate new audio file
    success = await tts_manager.synthesize(text, provider, voice, filepath)
    
    if success:
        return filename
    else:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to generate audio using {provider}"
        )

def get_base_url(request: Request) -> str:
    """Get the base URL for the API"""
    return f"{request.url.scheme}://{request.url.netloc}"

@app.get("/")
async def root():
    """Root endpoint with API information"""
    providers = tts_manager.get_available_providers()
    
    return {
        "message": "Multi-Provider Text-to-Speech API",
        "endpoints": {
            "/tts": "Generate audio from text (returns URL)",
            "/play/{filename}": "Stream audio file",
            "/files": "List all audio files",
            "/providers": "List available TTS providers",
            "/health": "Health check"
        },
        "available_providers": {
            name: {
                "voices": provider.voices,
                "enabled": provider.enabled
            }
            for name, provider in providers.items()
        }
    }

@app.get("/providers")
async def list_providers():
    """List all available TTS providers and their voices"""
    providers = tts_manager.get_available_providers()
    
    return {
        "providers": {
            name: {
                "voices": provider.voices,
                "enabled": provider.enabled
            }
            for name, provider in providers.items()
        }
    }

@app.get("/tts")
async def text_to_speech(
    request: Request,
    text: str = Query(..., description="Text to convert to speech", min_length=1, max_length=1000),
    provider: str = Query("pollinations", description="TTS provider to use"),
    voice: str = Query(None, description="Voice to use for speech synthesis")
):
    """
    Generate or retrieve MP3 audio file from text and return URL
    
    - **text**: The text to convert to speech (required)
    - **provider**: TTS provider to use (pollinations, espeak, festival, coqui)
    - **voice**: Voice to use (varies by provider)
    
    Returns JSON with the URL to access the audio file
    """
    # Check if provider is available
    if provider not in tts_manager.get_available_providers():
        available = list(tts_manager.get_available_providers().keys())
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider}' not available. Available providers: {', '.join(available)}"
        )
    
    # Get voices for the provider
    available_voices = tts_manager.get_provider_voices(provider)
    
    # Use first voice if none specified
    if voice is None:
        voice = available_voices[0] if available_voices else "default"
    
    # Validate voice
    if voice not in available_voices:
        raise HTTPException(
            status_code=400,
            detail=f"Voice '{voice}' not available for provider '{provider}'. Available voices: {', '.join(available_voices)}"
        )
    
    try:
        filename = await create_audio_file(text, provider, voice)
        base_url = get_base_url(request)
        audio_url = f"{base_url}/play/{filename}"
        
        return {
            "success": True,
            "message": "Audio generated successfully",
            "data": {
                "filename": filename,
                "url": audio_url,
                "text": text,
                "provider": provider,
                "voice": voice
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/play/{filename}")
async def play_audio_file(filename: str):
    """Stream a specific audio file for inline playback"""
    filepath = AUDIO_DIR / filename
    
    if not filepath.exists() or not filepath.name.endswith('.mp3'):
        raise HTTPException(status_code=404, detail="Audio file not found")
    
    with open(filepath, 'rb') as f:
        content = f.read()
    
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(len(content)),
        "Cache-Control": "public, max-age=3600",
        "Content-Disposition": "inline"
    }
    
    return Response(
        content=content,
        media_type="audio/mpeg", 
        headers=headers
    )

@app.get("/files")
async def list_audio_files(request: Request):
    """List all generated audio files with their URLs"""
    files = []
    base_url = get_base_url(request)
    
    for file in AUDIO_DIR.glob("*.mp3"):
        files.append({
            "filename": file.name,
            "url": f"{base_url}/play/{file.name}",
            "size": file.stat().st_size,
            "created": file.stat().st_mtime
        })
    return {"files": files, "total": len(files)}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    providers = tts_manager.get_available_providers()
    return {
        "status": "healthy", 
        "service": "Multi-Provider Text-to-Speech API",
        "providers_available": len(providers),
        "providers": list(providers.keys())
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8887)
