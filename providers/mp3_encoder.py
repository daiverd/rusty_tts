"""
In-process WAV/PCM -> MP3 encoding, replacing the per-request ffmpeg
subprocess spawn that used to sit in every provider's synthesis pipeline.

Benchmarked: ffmpeg's own process startup (~65ms, mostly dynamic-library
loading) was the single largest fixed cost in the whole pipeline for the
fast rule-based engines - bigger than DECtalk's entire synthesis (~47ms).
lameenc wraps libmp3lame directly with no subprocess involved, so that
startup tax disappears entirely.
"""

import array
import io
import math
import wave
from pathlib import Path
from typing import Tuple

import lameenc

_VBR_QUALITY = 2  # matches the old `-q:a 2` ffmpeg setting (0=best, 9=worst)


def parse_wav(wav_bytes: bytes) -> Tuple[bytes, int, int]:
    """Extract (pcm_s16le_bytes, sample_rate, channels) from a WAV container."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        sample_width = w.getsampwidth()
        channels = w.getnchannels()
        sample_rate = w.getframerate()
        pcm = w.readframes(w.getnframes())

    if sample_width == 1:
        # WAV's 8-bit PCM is unsigned (centered on 128), unlike every wider
        # width - SAM emits this. lameenc only accepts 16-bit, so widen it.
        unsigned = array.array('B')
        unsigned.frombytes(pcm)
        signed16 = array.array('h', ((b - 128) << 8 for b in unsigned))
        pcm = signed16.tobytes()
    elif sample_width != 2:
        # Every other engine on this path emits 16-bit PCM; if that ever
        # changes this needs a real conversion, not a silent wrong-format
        # encode.
        raise ValueError(f"Unsupported WAV sample width: {sample_width * 8}-bit")

    return pcm, sample_rate, channels


def normalize_pcm(pcm: bytes, target_dbfs: float = -20.0, max_gain_db: float = 12.0) -> bytes:
    """Approximate loudness normalization, replacing ffmpeg's `-af loudnorm`
    used by the retrochip/MAME providers (chip-emulator/real-hardware
    output loudness varies a lot by source voice). Not true EBU R128
    integrated loudness - a simple RMS-to-target gain, clamped so
    near-silent input isn't amplified into noise and peak-limited to avoid
    clipping - but serves the same practical goal (every voice on this
    path is audible)."""
    samples = array.array('h')
    samples.frombytes(pcm)
    if not samples:
        return pcm

    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    if rms < 1:
        return pcm

    target_amplitude = 32767 * (10 ** (target_dbfs / 20))
    gain = target_amplitude / rms
    gain = min(gain, 10 ** (max_gain_db / 20))

    peak = max(abs(s) for s in samples)
    if peak * gain > 32767:
        gain = 32767 / peak

    if gain <= 1.0:
        return pcm

    for i, s in enumerate(samples):
        samples[i] = max(-32768, min(32767, int(s * gain)))

    return samples.tobytes()


def encode_pcm_to_mp3(pcm: bytes, sample_rate: int, channels: int, output_path: Path,
                       normalize: bool = False, target_dbfs: float = -20.0) -> bool:
    try:
        if normalize:
            pcm = normalize_pcm(pcm, target_dbfs=target_dbfs)

        encoder = lameenc.Encoder()
        encoder.set_in_sample_rate(sample_rate)
        encoder.set_channels(channels)
        encoder.set_quality(_VBR_QUALITY)
        encoder.set_vbr(lameenc.VBR_RH)
        encoder.set_vbr_quality(_VBR_QUALITY)

        mp3_data = encoder.encode(pcm)
        mp3_data += encoder.flush()

        Path(output_path).write_bytes(mp3_data)
        return True
    except Exception:
        return False


def encode_wav_to_mp3(wav_bytes: bytes, output_path: Path) -> bool:
    try:
        pcm, sample_rate, channels = parse_wav(wav_bytes)
        return encode_pcm_to_mp3(pcm, sample_rate, channels, output_path)
    except Exception:
        return False
