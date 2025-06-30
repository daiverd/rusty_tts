# -*- coding: utf-8 -*-
"""
Balcon TTS Provider for Windows
Python 2.7 Compatible
"""

import subprocess
import tempfile
import os
import base64

class BalconProvider(object):
    """Balcon TTS Provider using balcon.exe"""
    
    def __init__(self, executable_path='balcon.exe'):
        self.executable_path = executable_path
        self.name = 'balcon'
        self.display_name = 'Balcon (Windows SAPI)'
        
    def is_available(self):
        """Check if balcon.exe is available"""
        return os.path.exists(self.executable_path)
    
    def get_voices(self):
        """Get list of available voices with SAPI version detection"""
        if not self.is_available():
            return []
        
        try:
            result = subprocess.check_output([self.executable_path, '-l'], 
                                           stderr=subprocess.STDOUT)
            
            voices = []
            for line in result.split('\n'):
                if line.strip():
                    voice_name = line.strip()
                    sapi_version = self._detect_sapi_version(voice_name)
                    voices.append({
                        'name': voice_name,
                        'provider': self.name,
                        'sapi_version': sapi_version,
                        'features': {
                            'raw_pcm': sapi_version == 5,
                            'volume_control': sapi_version == 5,
                            'rate_range': '0-100' if sapi_version == 4 else '-10 to 10',
                            'pitch_range': '0-100' if sapi_version == 4 else '-10 to 10',
                            'multi_language': sapi_version == 5
                        }
                    })
            
            return voices
            
        except subprocess.CalledProcessError:
            return []
    
    def _detect_sapi_version(self, voice_name):
        """Detect SAPI version for a specific voice"""
        try:
            test_cmd = [self.executable_path, '-n', voice_name, '-m']
            result = subprocess.check_output(test_cmd, stderr=subprocess.STDOUT)
            
            # Parse output to determine SAPI version
            result_lower = result.lower()
            if 'sapi 5' in result_lower or 'microsoft speech platform' in result_lower:
                return 5
            elif 'sapi 4' in result_lower:
                return 4
            else:
                # Try to detect by testing SAPI 5 features
                return self._test_sapi5_features(voice_name)
                
        except subprocess.CalledProcessError:
            return 4  # Default to SAPI 4 for safety
    
    def _test_sapi5_features(self, voice_name):
        """Test if voice supports SAPI 5 features"""
        try:
            # Test if voice supports volume parameter (SAPI 5 only)
            test_cmd = [
                self.executable_path,
                '-t', 'test',
                '-n', voice_name,
                '-v', '50',
                '-o'  # Try STDOUT output
            ]
            subprocess.check_output(test_cmd, stderr=subprocess.STDOUT)
            return 5
        except subprocess.CalledProcessError:
            return 4
    
    def synthesize(self, text, voice, rate=0, pitch=0, volume=100):
        """
        Synthesize text to speech
        Returns dict with audio data and format info
        """
        if not self.is_available():
            raise Exception("Balcon not available")
        
        # Ensure text is properly encoded
        if isinstance(text, unicode):
            text = text.encode('utf-8')
        
        sapi_version = self._detect_sapi_version(voice)
        
        # Try SAPI 5 raw PCM output first (most efficient)
        if sapi_version == 5:
            try:
                return self._synthesize_raw_pcm(text, voice, rate, pitch, volume)
            except subprocess.CalledProcessError:
                # Fall back to WAV file method
                pass
        
        # SAPI 4 or SAPI 5 fallback: WAV file output
        return self._synthesize_wav_file(text, voice, rate, pitch, volume, sapi_version)
    
    def _synthesize_raw_pcm(self, text, voice, rate, pitch, volume):
        """Synthesize using SAPI 5 raw PCM output"""
        cmd = [
            self.executable_path,
            '-t', text,
            '-n', voice,
            '-s', str(max(-10, min(10, rate))),
            '-p', str(max(-10, min(10, pitch))),
            '-v', str(max(0, min(100, volume))),
            '-o', '--raw',
            '-fr', '22',  # 22kHz sampling
            '-bt', '16',  # 16-bit
            '-ch', '1'    # Mono
        ]
        
        result = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        
        return {
            'audio_data': base64.b64encode(result),
            'format': 'raw_pcm',
            'sample_rate': 22050,
            'bit_depth': 16,
            'channels': 1,
            'sapi_version': 5
        }
    
    def _synthesize_wav_file(self, text, voice, rate, pitch, volume, sapi_version):
        """Synthesize using WAV file output"""
        tmp_wav = tempfile.mktemp(suffix='.wav')
        
        try:
            if sapi_version == 4:
                # SAPI 4: Convert rate/pitch from SAPI 5 ranges to SAPI 4 ranges
                # SAPI 5 range: -10 to 10, SAPI 4 range: 0 to 100
                sapi4_rate = max(0, min(100, 50 + rate * 5)) if rate != 0 else 50
                sapi4_pitch = max(0, min(100, 50 + pitch * 5)) if pitch != 0 else 50
                
                cmd = [
                    self.executable_path,
                    '-t', text,
                    '-n', voice,
                    '-s', str(sapi4_rate),
                    '-p', str(sapi4_pitch),
                    # Note: no volume parameter for SAPI 4
                    '-w', tmp_wav
                ]
            else:
                # SAPI 5 with WAV output
                cmd = [
                    self.executable_path,
                    '-t', text,
                    '-n', voice,
                    '-s', str(max(-10, min(10, rate))),
                    '-p', str(max(-10, min(10, pitch))),
                    '-v', str(max(0, min(100, volume))),
                    '-w', tmp_wav
                ]
            
            result = subprocess.call(cmd)
            
            if result == 0 and os.path.exists(tmp_wav):
                # Read WAV file
                with open(tmp_wav, 'rb') as f:
                    wav_data = f.read()
                
                os.unlink(tmp_wav)
                
                return {
                    'audio_data': base64.b64encode(wav_data),
                    'format': 'wav',
                    'sapi_version': sapi_version
                }
            else:
                if os.path.exists(tmp_wav):
                    os.unlink(tmp_wav)
                raise Exception("Balcon synthesis failed with return code: {}".format(result))
                
        except Exception as e:
            if os.path.exists(tmp_wav):
                os.unlink(tmp_wav)
            raise e
    
    def test_voice(self, voice_name):
        """Test if a voice works by generating a short sample"""
        try:
            result = self.synthesize("Test", voice_name)
            return True
        except Exception:
            return False
    
    def get_voice_info(self, voice_name):
        """Get detailed information about a specific voice"""
        if not self.is_available():
            return None
        
        try:
            # Get voice parameters
            cmd = [self.executable_path, '-n', voice_name, '-m']
            result = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            
            sapi_version = self._detect_sapi_version(voice_name)
            
            return {
                'name': voice_name,
                'provider': self.name,
                'sapi_version': sapi_version,
                'raw_info': result,
                'features': {
                    'raw_pcm': sapi_version == 5,
                    'volume_control': sapi_version == 5,
                    'rate_range': '0-100' if sapi_version == 4 else '-10 to 10',
                    'pitch_range': '0-100' if sapi_version == 4 else '-10 to 10',
                    'multi_language': sapi_version == 5
                },
                'working': self.test_voice(voice_name)
            }
            
        except subprocess.CalledProcessError:
            return None