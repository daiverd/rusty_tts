"""
Coqui TTS sidecar service.

Loads the Coqui models once at container startup and keeps them warm in
memory, so the main rusty_tts API doesn't pay the ~10s torch/model-load
tax (on top of genuinely slow CPU-bound neural synthesis) on every request.
"""

import base64
import logging
import tempfile
import threading
from typing import Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VOICES = [
    "tts_models/en/ljspeech/tacotron2-DDC",
    "tts_models/en/ljspeech/glow-tts",
]

app = FastAPI(title="Coqui TTS Sidecar")

_models: Dict[str, object] = {}
_load_lock = threading.Lock()
_synth_lock = threading.Lock()


def _load_models():
    from TTS.api import TTS

    for name in VOICES:
        logger.info(f"Loading {name}...")
        try:
            model = TTS(name, progress_bar=False)
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
        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
            model.tts_to_file(text=req.text, file_path=tmp.name)
            tmp.seek(0)
            wav_bytes = tmp.read()

    return {
        "success": True,
        "audio_data": base64.b64encode(wav_bytes).decode("ascii"),
        "format": "wav",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8891)
