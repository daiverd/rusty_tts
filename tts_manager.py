from typing import Dict, List
from pathlib import Path
from providers import (
    TTSProvider, BaseTTSEngine,
    PollinationsEngine, EspeakEngine, FestivalEngine, FliteEngine,
    DECtalkEngine, LPCEngine, SAMEngine, CoquiTTSEngine, WindowsEngine
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
            "pollinations": PollinationsEngine(),
            "espeak": EspeakEngine(),
            "festival": FestivalEngine(),
            "flite": FliteEngine(),
            "dectalk": DECtalkEngine(),
            "lpc": LPCEngine(),
            "sam": SAMEngine(),
            "coqui": CoquiTTSEngine(),
            "windows": WindowsEngine(),
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