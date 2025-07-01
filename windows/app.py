# -*- coding: utf-8 -*-
"""
Windows TTS Service - Python 2.7 Compatible
Provides HTTP API for balcon.exe and other Windows TTS engines
"""

from flask import Flask, request, jsonify
import subprocess
import json
import tempfile
import os
import base64
import hashlib
import sys

# Ensure we can handle unicode properly in Python 2.7
reload(sys)
sys.setdefaultencoding('utf-8')

app = Flask(__name__)

# Configuration
AUDIO_DIR = 'audio_files'
MAX_TEXT_LENGTH = 5000

# Ensure audio directory exists
if not os.path.exists(AUDIO_DIR):
    os.makedirs(AUDIO_DIR)

def generate_filename(text, provider, voice):
    """Generate consistent filename based on text, provider, and voice"""
    content = u'{}:{}:{}'.format(text, provider, voice).encode('utf-8')
    hash_obj = hashlib.md5(content)
    return hash_obj.hexdigest() + '.mp3'

def detect_voice_sapi_version(voice_name):
    """Detect if voice is SAPI 4 or SAPI 5 by testing features"""
    try:
        test_cmd = ['balcon.exe', '-n', voice_name, '-m']
        result = subprocess.check_output(test_cmd, stderr=subprocess.STDOUT)
        
        # Parse output to determine SAPI version
        if 'SAPI 5' in result or 'Microsoft Speech Platform' in result:
            return 5
        else:
            return 4
    except:
        return 4  # Default to SAPI 4 for safety

@app.route('/')
def index():
    """API information"""
    return jsonify({
        'name': 'Windows TTS Service',
        'version': '1.0.0',
        'platform': 'Windows XP/Python 2.7',
        'providers': ['balcon'],
        'endpoints': {
            '/tts': 'Generate TTS audio',
            '/providers': 'List available providers and voices',
            '/health': 'Service health check'
        }
    })

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'platform': 'Windows XP',
        'python_version': '2.7',
        'balcon_available': os.path.exists('balcon.exe')
    })

@app.route('/tts')
def tts():
    """Generate TTS audio - GET endpoint for compatibility"""
    text = request.args.get('text', '')
    provider = request.args.get('provider', 'balcon')
    voice = request.args.get('voice', 'Microsoft Sam')
    
    if not text:
        return jsonify({'error': 'No text provided'}), 400
    
    if len(text) > MAX_TEXT_LENGTH:
        return jsonify({'error': 'Text too long'}), 400
    
    # Generate filename
    filename = generate_filename(text, provider, voice)
    filepath = os.path.join(AUDIO_DIR, filename)
    
    # Check if file already exists (caching)
    if os.path.exists(filepath):
        return jsonify({'audio_url': '/play/' + filename})
    
    # Generate audio
    if provider == 'balcon':
        success = synthesize_balcon(text, voice, filepath)
        if success:
            return jsonify({'audio_url': '/play/' + filename})
        else:
            return jsonify({'error': 'TTS synthesis failed'}), 500
    else:
        return jsonify({'error': 'Unknown provider'}), 400

@app.route('/synthesize', methods=['POST'])
def synthesize():
    """Generate TTS audio - POST endpoint"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No JSON data provided'}), 400
    
    text = data.get('text', '').encode('utf-8') if isinstance(data.get('text', ''), unicode) else data.get('text', '')
    provider = data.get('provider', 'balcon')
    voice = data.get('voice', 'Microsoft Sam')
    rate = data.get('rate', 0)
    pitch = data.get('pitch', 0)
    volume = data.get('volume', 100)
    
    if not text:
        return jsonify({'error': 'No text provided'}), 400
    
    if len(text) > MAX_TEXT_LENGTH:
        return jsonify({'error': 'Text too long'}), 400
    
    if provider == 'balcon':
        return synthesize_balcon_advanced(text, voice, rate, pitch, volume)
    else:
        return jsonify({'error': 'Unknown provider'}), 400

def synthesize_balcon(text, voice, output_file):
    """Basic balcon synthesis for GET endpoint"""
    try:
        # Use WAV file approach for simplicity
        tmp_wav = tempfile.mktemp(suffix='.wav')
        
        cmd = [
            'balcon.exe',
            '-t', text,
            '-n', voice,
            '-w', tmp_wav
        ]
        
        result = subprocess.call(cmd)
        
        if result == 0 and os.path.exists(tmp_wav):
            # Convert WAV to MP3 (simplified - just copy for now)
            # In real implementation, you'd use FFmpeg here
            import shutil
            shutil.copy2(tmp_wav, output_file.replace('.mp3', '.wav'))
            os.unlink(tmp_wav)
            return True
        else:
            if os.path.exists(tmp_wav):
                os.unlink(tmp_wav)
            return False
            
    except Exception as e:
        return False

def synthesize_balcon_advanced(text, voice, rate, pitch, volume):
    """Advanced balcon synthesis with SAPI version detection"""
    try:
        sapi_version = detect_voice_sapi_version(voice)
        
        if sapi_version == 5:
            # SAPI 5: Try raw PCM output first
            try:
                cmd = [
                    'balcon.exe',
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
                
                # Return base64 encoded raw PCM
                return jsonify({
                    'success': True,
                    'audio_data': base64.b64encode(result),
                    'format': 'raw_pcm',
                    'sample_rate': 22050,
                    'bit_depth': 16,
                    'channels': 1,
                    'sapi_version': 5
                })
                
            except subprocess.CalledProcessError:
                # Fall back to WAV file method
                pass
        
        # SAPI 4 or SAPI 5 fallback: Use WAV file output
        tmp_wav = tempfile.mktemp(suffix='.wav')
        
        try:
            if sapi_version == 4:
                # SAPI 4: Convert rate/pitch from SAPI 5 ranges to SAPI 4 ranges
                cmd = [
                    'balcon.exe',
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
                
                cmd.extend(['-w', tmp_wav])
            else:
                # SAPI 5 with WAV output
                cmd = [
                    'balcon.exe',
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
                # Read WAV file and return as base64
                with open(tmp_wav, 'rb') as f:
                    wav_data = f.read()
                
                os.unlink(tmp_wav)
                
                return jsonify({
                    'success': True,
                    'audio_data': base64.b64encode(wav_data),
                    'format': 'wav',
                    'sapi_version': sapi_version
                })
            else:
                if os.path.exists(tmp_wav):
                    os.unlink(tmp_wav)
                return jsonify({'error': 'Balcon synthesis failed'}), 500
                
        except Exception as e:
            if os.path.exists(tmp_wav):
                os.unlink(tmp_wav)
            return jsonify({'error': str(e)}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/providers')
def providers():
    """List available providers and voices"""
    providers_data = {}
    
    # Balcon provider
    if os.path.exists('balcon.exe'):
        try:
            result = subprocess.check_output(['balcon.exe', '-l'], stderr=subprocess.STDOUT)
            
            voices = []
            for line in result.split('\n'):
                if line.strip():
                    voice_name = line.strip()
                    sapi_version = detect_voice_sapi_version(voice_name)
                    voices.append({
                        'name': voice_name,
                        'sapi_version': sapi_version,
                        'features': {
                            'raw_pcm': sapi_version == 5,
                            'volume_control': sapi_version == 5,
                            'rate_range': '0-100' if sapi_version == 4 else '-10 to 10',
                            'pitch_range': '0-100' if sapi_version == 4 else '-10 to 10'
                        }
                    })
            
            providers_data['balcon'] = {
                'name': 'Balcon (Windows SAPI)',
                'available': True,
                'voices': voices
            }
            
        except subprocess.CalledProcessError:
            providers_data['balcon'] = {
                'name': 'Balcon (Windows SAPI)',
                'available': False,
                'error': 'Failed to get voice list'
            }
    else:
        providers_data['balcon'] = {
            'name': 'Balcon (Windows SAPI)',
            'available': False,
            'error': 'balcon.exe not found'
        }
    
    return jsonify(providers_data)

@app.route('/play/<filename>')
def play_audio(filename):
    """Serve audio files"""
    filepath = os.path.join(AUDIO_DIR, filename)
    if os.path.exists(filepath):
        from flask import send_file
        return send_file(filepath, mimetype='audio/mpeg')
    else:
        return jsonify({'error': 'File not found'}), 404

@app.route('/files')
def list_files():
    """List generated audio files"""
    try:
        files = []
        for filename in os.listdir(AUDIO_DIR):
            if filename.endswith(('.mp3', '.wav')):
                filepath = os.path.join(AUDIO_DIR, filename)
                stat = os.stat(filepath)
                files.append({
                    'name': filename,
                    'size': stat.st_size,
                    'created': stat.st_ctime,
                    'url': '/play/' + filename
                })
        
        # Sort by creation time, newest first
        files.sort(key=lambda x: x['created'], reverse=True)
        return jsonify(files)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("Starting Windows TTS Service...")
    print("Platform: Windows XP / Python 2.7")
    print("Balcon available:", os.path.exists('balcon.exe'))
    
    app.run(host='0.0.0.0', port=5000, debug=False)