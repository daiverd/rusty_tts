# Balcon TTS Integration Architecture

## Overview

Balcon (Balabolka Command Line Utility) is a Windows-based TTS engine that uses Microsoft SAPI (Speech API) and Microsoft Speech Platform. This document outlines strategies for integrating balcon.exe as a secondary TTS service while maintaining the main Linux-based API.

## Balcon Capabilities

### Key Features
- **SAPI Integration**: Uses Microsoft Speech API v4.0/5.0 and Microsoft Speech Platform v11.0
- **Multiple Output Formats**: WAV output with configurable sampling rates (8-48kHz), bit depth (8/16-bit), channels (1/2)
- **Voice Control**: Access to all Windows TTS voices with different parameter ranges:
  - **SAPI 4**: Rate (0-100), Pitch (0-100), Volume (not supported)
  - **SAPI 5**: Rate (-10 to 10), Pitch (-10 to 10), Volume (0-100)
- **Advanced Features**: 
  - **Raw PCM output via STDOUT** (`-o` flag) - **SAPI 5 and Microsoft Speech Platform ONLY**
  - Multi-language support with automatic voice switching (SAPI 5 only)
  - Subtitle conversion with timing synchronization
  - Audio clip embedding
  - LRC/SRT subtitle generation

### Command Line Interface
```bash
# Basic synthesis (works for both SAPI 4 and 5)
balcon -t "Hello World" -w output.wav -n "Microsoft David"

# Raw PCM to STDOUT (SAPI 5 and Microsoft Speech Platform ONLY)
balcon -t "Hello World" -n "Microsoft David" -o --raw

# Voice listing (works for both SAPI 4 and 5)
balcon -l

# Multi-voice for foreign languages (SAPI 5 ONLY)
balcon -f text.txt -n "English Voice" --voice1-name "Spanish Voice" --voice1-langid es

# SAPI 4 rate/pitch example (different ranges)
balcon -t "Hello World" -w output.wav -n "SAPI4Voice" -s 50 -p 75

# SAPI 5 rate/pitch/volume example  
balcon -t "Hello World" -w output.wav -n "SAPI5Voice" -s -2 -p 1 -v 90
```

## Architecture Options

### Option 1: HTTP Proxy Bridge (Recommended)

**Architecture**: Linux Main API ↔ Windows Balcon Service (HTTP)

```
┌─────────────────┐    HTTP/JSON    ┌──────────────────┐
│   Linux API     │ ────────────────→ │  Windows Service │
│  (FastAPI)      │                  │   (balcon.exe)   │
│                 │ ←──────────────── │                  │
└─────────────────┘    Audio Stream  └──────────────────┘
```

**Implementation**:
- Create a lightweight HTTP service on Windows that wraps balcon.exe
- Linux API makes HTTP requests to Windows service
- Windows service returns audio data via HTTP response
- Caching handled on Linux side

**Pros**:
- Clean separation of concerns
- Network-based, works across machines
- Can scale to multiple Windows instances
- Consistent with existing architecture

**Cons**:
- Network latency overhead
- Requires Windows machine to be always available
- Additional service to maintain

### Option 2: Shared Network Storage

**Architecture**: Linux Main API ↔ Shared Storage ↔ Windows Balcon Service

```
┌─────────────────┐    Write Job     ┌──────────────────┐
│   Linux API     │ ────────────────→ │ Shared Storage   │
│  (FastAPI)      │                  │  (NFS/SMB/etc)   │
│                 │ ←──────────────── │                  │
└─────────────────┘    Read Result   └──────────────────┘
                                            ↕
                                     ┌──────────────────┐
                                     │  Windows Service │
                                     │   (balcon.exe)   │
                                     └──────────────────┘
```

**Implementation**:
- Linux API writes job files to shared storage
- Windows service polls for new jobs
- Windows service processes jobs and writes results
- Linux API polls for completed results

**Pros**:
- Decoupled processing
- Can handle high volumes with queuing
- Both services can restart independently

**Cons**:
- Complex job management
- Potential file system conflicts
- Higher latency due to polling

### Option 3: Direct SSH/Remote Execution

**Architecture**: Linux Main API → SSH → Windows Machine

```
┌─────────────────┐    SSH Command   ┌──────────────────┐
│   Linux API     │ ────────────────→ │  Windows Machine │
│  (FastAPI)      │                  │   (balcon.exe)   │
│                 │ ←──────────────── │                  │
└─────────────────┘    STDOUT/File   └──────────────────┘
```

**Implementation**:
- Linux API executes balcon.exe via SSH
- Audio returned via STDOUT or file transfer
- No persistent Windows service needed

**Pros**:
- Simple implementation
- No additional Windows service
- Direct command execution

**Cons**:
- SSH overhead for each request
- Security concerns with SSH keys
- No connection pooling

## Recommended Implementation: HTTP Proxy Bridge

### Windows Service Architecture

```python
# windows_balcon_service.py
from flask import Flask, request, jsonify, Response
import subprocess
import tempfile
import os

app = Flask(__name__)

@app.route('/synthesize', methods=['POST'])
def synthesize():
    data = request.json
    text = data.get('text')
    voice = data.get('voice', 'Microsoft David')
    rate = data.get('rate', 0)
    pitch = data.get('pitch', 0)
    volume = data.get('volume', 100)
    
    # Detect if voice is SAPI 4 or SAPI 5
    voice_info = get_voice_info(voice)
    is_sapi5 = voice_info.get('sapi_version') == 5
    
    if is_sapi5:
        # SAPI 5: Use raw PCM output to STDOUT for efficient piping
        cmd = [
            'balcon.exe',
            '-t', text,
            '-n', voice,
            '-s', str(max(-10, min(10, rate))),  # Clamp to SAPI 5 range
            '-p', str(max(-10, min(10, pitch))), # Clamp to SAPI 5 range
            '-v', str(max(0, min(100, volume))), # SAPI 5 supports volume
            '-o', '--raw',
            '-fr', '22',  # 22kHz sampling
            '-bt', '16',  # 16-bit
            '-ch', '1'    # Mono
        ]
        
        result = subprocess.run(cmd, capture_output=True)
        
        if result.returncode == 0:
            # Convert raw PCM to MP3 using FFmpeg
            return convert_pcm_to_mp3(result.stdout)
        else:
            return jsonify({'error': result.stderr.decode()}), 500
    
    else:
        # SAPI 4: Must use WAV file output, no STDOUT support
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_wav:
            cmd = [
                'balcon.exe',
                '-t', text,
                '-n', voice,
                '-s', str(max(0, min(100, rate))),   # SAPI 4 range 0-100
                '-p', str(max(0, min(100, pitch))),  # SAPI 4 range 0-100
                # Note: -v not supported for SAPI 4
                '-w', tmp_wav.name
            ]
            
            result = subprocess.run(cmd, capture_output=True)
            
            if result.returncode == 0:
                # Read WAV file and convert to MP3
                with open(tmp_wav.name, 'rb') as f:
                    wav_data = f.read()
                os.unlink(tmp_wav.name)
                return convert_wav_to_mp3(wav_data)
            else:
                os.unlink(tmp_wav.name)
                return jsonify({'error': result.stderr.decode()}), 500

@app.route('/voices', methods=['GET'])
def get_voices():
    # Execute balcon -l to get voice list
    result = subprocess.run(['balcon.exe', '-l'], capture_output=True, text=True)
    if result.returncode == 0:
        voices = parse_voice_list(result.stdout)
        return jsonify(voices)
    return jsonify({'error': 'Failed to get voices'}), 500
```

### Linux Integration

```python
# providers/balcon.py
import requests
from .base import BaseTTSEngine

class BalconEngine(BaseTTSEngine):
    def __init__(self, windows_service_url):
        self.windows_service_url = windows_service_url
        super().__init__()
    
    def is_available(self):
        try:
            response = requests.get(f"{self.windows_service_url}/health", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def synthesize(self, text, voice, filename):
        try:
            payload = {
                'text': text,
                'voice': voice,
                'rate': 0,  # configurable
                'pitch': 0,  # configurable  
                'volume': 100  # configurable
            }
            
            response = requests.post(
                f"{self.windows_service_url}/synthesize",
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                with open(filename, 'wb') as f:
                    f.write(response.content)
                return True
            else:
                return False
                
        except Exception as e:
            print(f"Balcon synthesis error: {e}")
            return False
    
    def get_voices(self):
        try:
            response = requests.get(f"{self.windows_service_url}/voices", timeout=10)
            if response.status_code == 200:
                return response.json()
            return []
        except:
            return []
```

## Configuration

### Environment Variables
```bash
# Linux side
BALCON_SERVICE_URL=http://windows-machine:5000
BALCON_ENABLED=true

# Windows side  
BALCON_SERVICE_PORT=5000
BALCON_EXECUTABLE_PATH=C:\path\to\balcon.exe
```

### Docker Compose Extension
```yaml
# docker-compose.balcon.yml
services:
  rusty-tts:
    environment:
      - BALCON_SERVICE_URL=http://balcon-service:5000
      - BALCON_ENABLED=true
  
  # Note: This would need to run on a Windows Docker host
  balcon-service:
    image: windows-balcon-service:latest
    ports:
      - "5000:5000"
    volumes:
      - ./providers/balcon:/app/balcon
```

## SAPI 4 vs SAPI 5 Considerations

### Key Differences

| Feature | SAPI 4 | SAPI 5 & Microsoft Speech Platform |
|---------|--------|-------------------------------------|
| **Raw PCM Output** | ❌ Not supported | ✅ Supported (`-o --raw`) |
| **Rate Range** | 0-100 | -10 to 10 |
| **Pitch Range** | 0-100 | -10 to 10 |
| **Volume Control** | ❌ Not supported | ✅ 0-100 |
| **Multi-language** | ❌ Not supported | ✅ Supported |
| **Output Method** | WAV files only | STDOUT or WAV files |

### Implementation Strategy

For **SAPI 5 voices**: Use the efficient raw PCM pipeline (`-o --raw`) that pipes directly to FFmpeg for MP3 conversion, matching the existing engine pattern.

For **SAPI 4 voices**: Fall back to WAV file generation with temporary files, then convert to MP3. This requires:
- Temporary file management
- File I/O overhead
- Different parameter ranges (0-100 vs -10 to 10)

### Voice Detection

The Windows service will need to detect SAPI version per voice. This can be done by:
1. Parsing the output of `balcon -l` for voice characteristics
2. Testing a voice with SAPI 5 features and falling back on failure
3. Maintaining a voice-to-SAPI-version mapping

## Windows XP VM Deployment Option

### Advantages of Windows XP VM

- **Maximum SAPI Compatibility**: Windows XP supports both SAPI 4 and SAPI 5, providing access to the widest range of classic TTS voices
- **Minimal Resource Usage**: XP VMs run efficiently with 512MB-1GB RAM vs modern Windows requiring 4GB+
- **Small Disk Footprint**: Minimal XP installation ~2GB vs 20GB+ for modern Windows
- **Security Isolation**: Legacy OS provides natural security boundary for TTS processing
- **Classic Voice Access**: Access to vintage SAPI 4 voices that may not be available on modern systems

### Python 2.7 Implementation Considerations

Since Windows XP predates Python 3 widespread adoption, Python 2.7 becomes the practical choice:

**Available Libraries**:
- Flask 0.12.x (last version supporting Python 2.7)
- `json` module (built-in)
- `subprocess` module (different API than Python 3)
- `tempfile` module (built-in)

**Unicode Handling**: Requires careful `.encode('utf-8')` for international text.

### XP-Compatible Service Implementation

```python
# balcon_service_xp.py - Python 2.7 compatible
from flask import Flask, request, jsonify, send_file
import subprocess
import json
import tempfile
import os
import base64

app = Flask(__name__)

def detect_voice_sapi_version(voice_name):
    """Detect if voice is SAPI 4 or SAPI 5 by testing features"""
    # Try SAPI 5 feature first
    test_cmd = ['balcon.exe', '-n', voice_name, '-m']
    try:
        result = subprocess.check_output(test_cmd, stderr=subprocess.STDOUT)
        # Parse output to determine SAPI version
        if 'SAPI 5' in result or 'Microsoft Speech Platform' in result:
            return 5
        else:
            return 4
    except:
        return 4  # Default to SAPI 4 for safety

@app.route('/synthesize', methods=['POST'])
def synthesize():
    data = request.get_json()
    text = data.get('text', '').encode('utf-8')
    voice = data.get('voice', 'Microsoft Sam')
    rate = data.get('rate', 0)
    pitch = data.get('pitch', 0)
    volume = data.get('volume', 100)
    
    sapi_version = detect_voice_sapi_version(voice)
    
    if sapi_version == 5:
        # SAPI 5: Use raw PCM output when possible
        try:
            cmd = [
                'balcon.exe',
                '-t', text,
                '-n', voice,
                '-s', str(max(-10, min(10, rate))),
                '-p', str(max(-10, min(10, pitch))),
                '-v', str(max(0, min(100, volume))),
                '-o', '--raw',
                '-fr', '22',
                '-bt', '16',
                '-ch', '1'
            ]
            
            result = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            
            # Return base64 encoded raw PCM for Linux to convert to MP3
            return jsonify({
                'success': True,
                'audio_data': base64.b64encode(result),
                'format': 'raw_pcm',
                'sample_rate': 22050,
                'bit_depth': 16,
                'channels': 1
            })
            
        except subprocess.CalledProcessError:
            # Fall back to WAV file method
            pass
    
    # SAPI 4 or SAPI 5 fallback: Use WAV file output
    tmp_wav = tempfile.mktemp(suffix='.wav')
    
    try:
        if sapi_version == 4:
            # SAPI 4 parameter ranges
            cmd = [
                'balcon.exe',
                '-t', text,
                '-n', voice,
                '-s', str(max(0, min(100, rate if rate >= 0 else 50))),
                '-p', str(max(0, min(100, pitch if pitch >= 0 else 50))),
                '-w', tmp_wav
            ]
        else:
            # SAPI 5 with WAV output
            cmd = [
                'balcon.exe',
                '-t', text,
                '-n', voice,
                '-s', str(max(-10, min(10, rate))),
                '-p', str(max(-10, min(10, pitch))),
                '-v', str(max(0, min(100, volume))),
                '-w', tmp_wav
            ]
        
        subprocess.check_call(cmd)
        
        # Read WAV file and return as base64
        with open(tmp_wav, 'rb') as f:
            wav_data = f.read()
        
        os.unlink(tmp_wav)
        
        return jsonify({
            'success': True,
            'audio_data': base64.b64encode(wav_data),
            'format': 'wav'
        })
        
    except subprocess.CalledProcessError as e:
        if os.path.exists(tmp_wav):
            os.unlink(tmp_wav)
        return jsonify({'error': str(e)}), 500

@app.route('/voices', methods=['GET'])
def get_voices():
    try:
        result = subprocess.check_output(['balcon.exe', '-l'], 
                                       stderr=subprocess.STDOUT)
        
        # Parse voice list and detect SAPI versions
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
        
        return jsonify({'voices': voices})
        
    except subprocess.CalledProcessError as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'platform': 'Windows XP', 'python': '2.7'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
```

### Linux Integration Updates

```python
# providers/balcon.py - Updated for XP VM integration
import requests
import base64
import tempfile
import os
from .base import BaseTTSEngine

class BalconEngine(BaseTTSEngine):
    def __init__(self, xp_service_url='http://xp-vm:5000'):
        self.xp_service_url = xp_service_url
        super().__init__()
    
    def synthesize(self, text, voice, filename):
        try:
            payload = {
                'text': text,
                'voice': voice,
                'rate': 0,
                'pitch': 0,
                'volume': 100
            }
            
            response = requests.post(
                f"{self.xp_service_url}/synthesize",
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                audio_data = base64.b64decode(data['audio_data'])
                
                if data['format'] == 'raw_pcm':
                    # Convert raw PCM to MP3 using existing pipeline
                    return self._convert_pcm_to_mp3(
                        audio_data, 
                        data['sample_rate'],
                        data['bit_depth'],
                        data['channels'],
                        filename
                    )
                else:
                    # Convert WAV to MP3
                    return self._convert_wav_to_mp3(audio_data, filename)
            
            return False
            
        except Exception as e:
            print(f"Balcon XP synthesis error: {e}")
            return False
```

### VM Deployment Configuration

```yaml
# docker-compose.balcon-xp.yml
services:
  rusty-tts:
    environment:
      - BALCON_SERVICE_URL=http://xp-vm:5000
      - BALCON_ENABLED=true
  
  # Note: XP VM would be managed separately, not in Docker
  # This is just for reference
  xp-vm-bridge:
    image: nginx:alpine
    ports:
      - "5000:5000"
    volumes:
      - ./nginx-xp-proxy.conf:/etc/nginx/nginx.conf:ro
    # Proxy to actual XP VM at internal IP
```

## Implementation Phases

### Phase 1: Basic HTTP Service
1. Create minimal Windows HTTP service using Flask
2. Implement `/synthesize` endpoint with basic text-to-audio
3. Add voice listing endpoint
4. Test with curl/Postman

### Phase 2: Linux Integration
1. Create BalconEngine class following existing pattern
2. Add balcon provider to TTSManager
3. Implement error handling and fallbacks
4. Add configuration options

### Phase 3: Production Hardening
1. Add authentication/API keys
2. Implement rate limiting
3. Add monitoring and health checks
4. Create deployment scripts

### Phase 4: Advanced Features
1. Multi-language voice switching
2. SSML support via balcon tags
3. Subtitle generation integration
4. Audio effects via SoundTouch library

## Security Considerations

- **API Authentication**: Use API keys between services
- **Network Security**: VPN or secure network for service communication
- **Input Validation**: Sanitize text input to prevent command injection
- **Resource Limits**: Implement request timeouts and size limits
- **Process Isolation**: Run balcon.exe with minimal privileges

## Monitoring & Observability

- **Health Checks**: Regular service availability checks
- **Performance Metrics**: Response times, success rates
- **Error Logging**: Detailed error logging on both sides
- **Audio Quality**: Sample rate validation and format checks

## Testing Strategy

- **Unit Tests**: Test individual components in isolation
- **Integration Tests**: End-to-end workflow testing
- **Performance Tests**: Load testing with multiple concurrent requests
- **Failover Tests**: Service unavailability scenarios