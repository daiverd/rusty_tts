from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
import hashlib
from pathlib import Path
from tts_manager import TTSManager
from config import CORS_ORIGINS, AUDIO_DIR

app = FastAPI(title="Text-to-Speech API", description="Generate MP3 audio from text using multiple providers")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Length", "Content-Range", "Accept-Ranges"]
)

# Create audio directory
audio_dir = Path(AUDIO_DIR)
audio_dir.mkdir(exist_ok=True)


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
    filepath = audio_dir / filename
    
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

def format_provider_data(providers):
    """Format provider data for API responses"""
    return {
        name: {
            "voices": provider.voices,
            "enabled": provider.enabled
        }
        for name, provider in providers.items()
    }

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
        "available_providers": format_provider_data(providers)
    }

@app.get("/providers")
async def list_providers():
    """List all available TTS providers and their voices"""
    providers = tts_manager.get_available_providers()
    
    return {
        "providers": format_provider_data(providers)
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
        
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail="Audio generation failed: missing system dependency")
    except PermissionError as e:
        raise HTTPException(status_code=500, detail="Audio generation failed: insufficient permissions")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Audio generation failed: {str(e)}")

@app.get("/play/{filename}")
async def play_audio_file(filename: str):
    """Stream a specific audio file for inline playback"""
    filepath = audio_dir / filename
    
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
    
    for file in audio_dir.glob("*.mp3"):
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
