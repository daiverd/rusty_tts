"""
Piper TTS sidecar service.

Piper is CPU-fast (unlike Coqui) but still pays a ~1.7s onnxruntime-import +
model-load tax per request when run as a fresh CLI process. This service
loads every voice once at startup and keeps them warm in memory, and gives
Piper's voice catalog its own lightweight, independently rebuildable image
instead of being baked into the (much heavier) main app image.
"""

import base64
import io
import logging
import threading
import wave
from typing import Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VOICES = ["en_US-lessac-medium", "en_US-amy-medium", "en_GB-alan-medium"]
VOICES_DIR = "/opt/piper/voices"

app = FastAPI(title="Piper TTS Sidecar")

_models: Dict[str, object] = {}
_load_lock = threading.Lock()
_synth_lock = threading.Lock()


def _load_models():
    from piper import PiperVoice

    for name in VOICES:
        logger.info(f"Loading {name}...")
        try:
            model = PiperVoice.load(f"{VOICES_DIR}/{name}.onnx")
        except Exception:
            logger.exception(f"Failed to load {name}, skipping it")
            continue
        with _load_lock:
            _models[name] = model
        logger.info(f"Loaded {name}")


@app.on_event("startup")
def startup():
    threading.Thread(target=_load_models, daemon=True).start()


class SynthesizeRequest(BaseModel):
    text: str
    voice: str


@app.get("/health")
def health():
    with _load_lock:
        loaded = list(_models.keys())
    ready = len(loaded) == len(VOICES)
    if not ready:
        raise HTTPException(status_code=503, detail={"status": "loading", "loaded_models": loaded})
    return {"status": "ok", "loaded_models": loaded}


@app.get("/voices")
def voices():
    return {"voices": VOICES}


@app.post("/synthesize")
def synthesize(req: SynthesizeRequest):
    if req.voice not in VOICES:
        raise HTTPException(status_code=400, detail=f"Unknown voice: {req.voice}")

    with _load_lock:
        model = _models.get(req.voice)
    if model is None:
        raise HTTPException(status_code=503, detail="Model still loading")

    with _synth_lock:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            model.synthesize_wav(req.text, wf)

    return {
        "success": True,
        "audio_data": base64.b64encode(buf.getvalue()).decode("ascii"),
        "format": "wav",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8892)
