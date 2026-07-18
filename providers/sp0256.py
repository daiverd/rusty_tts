import subprocess
from pathlib import Path
from typing import List

from . import BaseTTSEngine, run_tts_pipeline_stdin_raw
from .phoneme_maps import get_g2p
from .phoneme_maps.sp0256 import arpabet_to_allophones, allophones_to_bytes

# SP0256-AL2 boards commonly clock the chip at 3.12MHz; with the chip's
# internal /336 divider that's ~9286Hz, widely rounded to ~10kHz in
# enthusiast documentation. Must match native/retrochip/main.cpp's
# run_sp0256() sample rate.
_SAMPLE_RATE = 10000

# ROM is proprietary (GI mask ROM dump) and not committed to this repo -
# see scripts/fetch_roms.sh. is_available() gates on its presence, same
# convention as every other engine when its dependency is missing.
_ROM_PATH = Path(__file__).resolve().parent.parent / "roms" / "sp0256-al2.bin"


class Sp0256Engine(BaseTTSEngine):
    """GI SP0256-AL2 allophone speech chip, driven by a standalone port of
    MAME's sp0256 core (native/retrochip). Text is converted to ARPAbet
    phonemes via g2p_en (CMU Pronouncing Dictionary based), then mapped to
    SP0256-AL2 allophone addresses (see providers/phoneme_maps/sp0256.py) -
    a best-effort mapping, not a period-accurate reproduction of the
    original Echo/Textalker driver."""

    def get_voices(self) -> List[str]:
        return ["default"]

    def is_available(self) -> bool:
        if not _ROM_PATH.exists():
            return False
        try:
            subprocess.run(["retrochip", "--chip", "sp0256", "--rom", str(_ROM_PATH)],
                            input=b"", capture_output=True)
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
            get_g2p()
            return True
        except Exception:
            return False

    async def synthesize(self, text: str, voice: str, output_path: Path) -> bool:
        try:
            tokens = get_g2p()(text)
            if not tokens:
                return False

            codes = arpabet_to_allophones(tokens)
            if not codes:
                return False
            code_bytes = allophones_to_bytes(codes)

            retrochip_cmd = ["retrochip", "--chip", "sp0256", "--rom", str(_ROM_PATH)]
            return run_tts_pipeline_stdin_raw(
                retrochip_cmd, code_bytes, output_path,
                sample_rate=_SAMPLE_RATE, channels=1
            )
        except Exception:
            return False
