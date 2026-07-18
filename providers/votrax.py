import subprocess
from pathlib import Path
from typing import List

from . import BaseTTSEngine, run_tts_pipeline_stdin_raw
from .phoneme_maps import get_g2p
from .phoneme_maps.votrax import arpabet_to_phones, phones_to_bytes

# Must match native/retrochip/votrax.h's default main_clock (720kHz, the
# reference "Votrax Personal Speech System" clock): sample rate = clock/18.
_SAMPLE_RATE = 40000

# ROM is proprietary (Votrax mask ROM dump) and not committed to this repo -
# see scripts/fetch_roms.sh. is_available() gates on its presence, same
# convention as every other engine when its dependency is missing.
_ROM_PATH = Path(__file__).resolve().parent.parent / "roms" / "sc01a.bin"


class VotraxEngine(BaseTTSEngine):
    """Votrax SC-01A allophone speech chip, driven by a standalone port of
    MAME's votrax core (native/retrochip). Text is converted to ARPAbet
    phonemes via g2p_en (CMU Pronouncing Dictionary based), then mapped to
    Votrax phone code(s) (see providers/phoneme_maps/votrax.py) - a
    best-effort mapping, not a period-accurate reproduction of any original
    Votrax text-to-phoneme hardware/software."""

    def get_voices(self) -> List[str]:
        return ["default"]

    def is_available(self) -> bool:
        if not _ROM_PATH.exists():
            return False
        try:
            subprocess.run(["retrochip", "--chip", "votrax", "--rom", str(_ROM_PATH)],
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

            codes = arpabet_to_phones(tokens)
            if not codes:
                return False
            code_bytes = phones_to_bytes(codes)

            retrochip_cmd = ["retrochip", "--chip", "votrax", "--rom", str(_ROM_PATH)]
            return run_tts_pipeline_stdin_raw(
                retrochip_cmd, code_bytes, output_path,
                sample_rate=_SAMPLE_RATE, channels=1
            )
        except Exception:
            return False
