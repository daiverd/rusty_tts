from typing import Dict, List
from pathlib import Path
from providers import (
    TTSProvider, BaseTTSEngine,
    EspeakEngine, FestivalEngine, FliteEngine,
    DECtalkEngine, SAMEngine, PiperEngine, CoquiTTSEngine, WindowsEngine,
    Tms5220Engine, Sp0256Engine, VotraxEngine, TextalkerEngine,
    VotraxTypeNTalkEngine, VotraxPersonalSpeechSystemEngine, SnSpellEngine,
    S14001aCalculatorEngine, DoubleTalkEngine, SmoothTalkerEngine,
    BestSpeechEngine, BestSpeechLangEngine, EloquenceEngine, WinTalkerEngine,
    MonologueEngine, SoftVoiceEngine, AmigaNarratorEngine
)


class TTSManager:
    """Manages multiple TTS engines"""
    
    def __init__(self):
        self.engines: Dict[str, BaseTTSEngine] = {}
        self.providers: Dict[str, TTSProvider] = {}
        self._initialize_engines()
    
    def _initialize_engines(self):
        """Initialize all available TTS engines"""
        engines = {
            "espeak": EspeakEngine(),
            "festival": FestivalEngine(),
            "flite": FliteEngine(),
            "dectalk": DECtalkEngine(),
            "sam": SAMEngine(),
            "piper": PiperEngine(),
            "coqui": CoquiTTSEngine(),
            "windows": WindowsEngine(),
            "sp0256": Sp0256Engine(),
            "votrax": VotraxEngine(),
            "textalker": TextalkerEngine(),
            "votrax_tnt": VotraxTypeNTalkEngine(),
            "votrax_pss": VotraxPersonalSpeechSystemEngine(),
            "snspell": SnSpellEngine(),
            "s14001a_calculator": S14001aCalculatorEngine(),
            "doubletalk": DoubleTalkEngine(),
            "smoothtalker": SmoothTalkerEngine(),
            "bestspeech": BestSpeechEngine(),
            "bestspeech_lang": BestSpeechLangEngine(),
            "eloquence": EloquenceEngine(),
            "wintalker": WinTalkerEngine(),
            "monologue": MonologueEngine(),
            "softvoice": SoftVoiceEngine(),
            "amiganarrator": AmigaNarratorEngine(),
            # tms5220 is intentionally not registered: LPC-resynthesis of
            # another engine's audio through the chip (see providers/tms5220.py)
            # is functional but doesn't sound good (sibilant/fricative sounds
            # frequently trigger a loud "LPC whistle", a real vocoder artifact
            # that's hard to tune away without hurting fidelity elsewhere).
            # Revisit if driven by real historical vocabulary ROM data instead.
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