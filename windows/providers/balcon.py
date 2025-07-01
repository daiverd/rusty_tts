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
            current_sapi = None
            
            for line in result.split('\n'):
                line = line.strip()
                if not line:
                    continue
                
                # Check for SAPI section headers
                if line.startswith('SAPI 4:'):
                    current_sapi = 4
                    continue
                elif line.startswith('SAPI 5:'):
                    current_sapi = 5
                    continue
                
                # Skip lines that don't contain voice information
                if current_sapi is None:
                    continue
                
                # Parse voice information
                if current_sapi == 4:
                    # SAPI 4 format: "Alex :: Adult Male #8, American English (TruVoice)"
                    if '::' in line:
                        voice_name = line.split('::')[0].strip()
                        description = line.split('::')[1].strip() if '::' in line else ''
                    else:
                        # Skip section headers and invalid lines
                        continue
                    
                    voices.append({
                        'name': voice_name,
                        'provider': self.name,
                        'sapi_version': 4,
                        'description': description,
                        'features': {
                            'raw_pcm': False,
                            'volume_control': False,
                            'rate_range': '0-100',
                            'pitch_range': '0-100',
                            'multi_language': False
                        }
                    })
                    
                elif current_sapi == 5:
                    # SAPI 5 format: Simple voice name like "Microsoft Sam"
                    voice_name = line.strip()
                    # Skip empty lines and section headers
                    if voice_name and not voice_name.endswith(':'):
                        voices.append({
                            'name': voice_name,
                            'provider': self.name,
                            'sapi_version': 5,
                            'description': '',
                            'features': {
                                'raw_pcm': True,
                                'volume_control': True,
                                'rate_range': '-10 to 10',
                                'pitch_range': '-10 to 10',
                                'multi_language': True
                            }
                        })
            
            return voices
            
        except subprocess.CalledProcessError:
            return []
    
    def _get_voice_sapi_version(self, voice_name):
        """Get SAPI version for a voice from the voice list"""
        voices = self.get_voices()
        for voice_info in voices:
            if voice_info['name'] == voice_name:
                return voice_info['sapi_version']
        # Default to SAPI 4 for safety if voice not found
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
        
        sapi_version = self._get_voice_sapi_version(voice)
        
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
            '-n', voice
        ]
        
        # Only add rate if non-default
        if rate != 0:
            cmd.extend(['-s', str(max(-10, min(10, rate)))])
        
        # Only add pitch if non-default  
        if pitch != 0:
            cmd.extend(['-p', str(max(-10, min(10, pitch)))])
        
        # Only add volume if non-default
        if volume != 100:
            cmd.extend(['-v', str(max(0, min(100, volume)))])
        
        cmd.extend(['-o', '--raw'])
        
        result = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        
        return {
            'audio_data': base64.b64encode(result),
            'format': 'raw_pcm',
            'sample_rate': 22050,  # Default SAPI 5 sample rate
            'bit_depth': 16,       # Default SAPI 5 bit depth
            'channels': 1,         # Default mono output
            'sapi_version': 5
        }
    
    def _synthesize_wav_file(self, text, voice, rate, pitch, volume, sapi_version):
        """Synthesize using WAV file output"""
        tmp_wav = tempfile.mktemp(suffix='.wav')
        
        try:
            if sapi_version == 4:
                # SAPI 4: Convert rate/pitch from SAPI 5 ranges to SAPI 4 ranges
                # SAPI 5 range: -10 to 10, SAPI 4 range: 0 to 100 (50 = normal)
                cmd = [
                    self.executable_path,
                    '-t', text,
                    '-n', voice
                ]
                
                # Only add rate if non-default
                if rate != 0:
                    sapi4_rate = max(0, min(100, 50 + rate * 5))
                    cmd.extend(['-s', str(sapi4_rate)])
                
                # Only add pitch if non-default  
                if pitch != 0:
                    sapi4_pitch = max(0, min(100, 50 + pitch * 5))
                    cmd.extend(['-p', str(sapi4_pitch)])
                
                # Note: SAPI 4 does not support volume parameter
                cmd.extend(['-w', tmp_wav])
            else:
                # SAPI 5 with WAV output
                cmd = [
                    self.executable_path,
                    '-t', text,
                    '-n', voice
                ]
                
                # Only add rate if non-default
                if rate != 0:
                    cmd.extend(['-s', str(max(-10, min(10, rate)))])
                
                # Only add pitch if non-default  
                if pitch != 0:
                    cmd.extend(['-p', str(max(-10, min(10, pitch)))])
                
                # Only add volume if non-default
                if volume != 100:
                    cmd.extend(['-v', str(max(0, min(100, volume)))])
                
                cmd.extend(['-w', tmp_wav])
            
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
            
            sapi_version = self._get_voice_sapi_version(voice_name)
            
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