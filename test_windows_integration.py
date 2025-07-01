#!/usr/bin/env python3
"""
Test script for Windows TTS integration
"""

import os
import sys
import time
import requests
import asyncio
from pathlib import Path

# Add current directory to path so we can import our modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from providers.windows import WindowsEngine
from tts_manager import TTSManager
from config import WINDOWS_TTS_URL, WINDOWS_TTS_TIMEOUT, WINDOWS_TTS_ENABLED

def test_windows_service_health():
    """Test if Windows service is responding"""
    print("Testing Windows service health...")
    
    try:
        response = requests.get(f"{WINDOWS_TTS_URL}/health", timeout=WINDOWS_TTS_TIMEOUT)
        if response.status_code == 200:
            data = response.json()
            print(f"✓ Windows service is healthy: {data}")
            return True
        else:
            print(f"✗ Windows service returned status {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Windows service is not available: {e}")
        return False

def test_windows_service_providers():
    """Test getting providers from Windows service"""
    print("\nTesting Windows service providers...")
    
    try:
        response = requests.get(f"{WINDOWS_TTS_URL}/providers", timeout=WINDOWS_TTS_TIMEOUT)
        if response.status_code == 200:
            data = response.json()
            print(f"✓ Windows providers: {list(data.keys())}")
            
            for provider_name, provider_data in data.items():
                if provider_data.get('available'):
                    voices = provider_data.get('voices', [])
                    print(f"  {provider_name}: {len(voices)} voices")
                    if voices:
                        print(f"    Sample voices: {[v['name'] for v in voices[:3]]}")
            return True
        else:
            print(f"✗ Windows service returned status {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Error getting Windows providers: {e}")
        return False

async def test_windows_engine():
    """Test Windows engine directly"""
    print("\nTesting Windows engine...")
    
    try:
        engine = WindowsEngine()
        
        # Test availability
        available = engine.is_available()
        print(f"Windows engine available: {available}")
        
        if not available:
            print("✗ Windows engine not available - check WINDOWS_TTS_ENABLED config")
            return False
        
        # Test getting voices
        voices = engine.get_voices()
        print(f"✓ Found {len(voices)} Windows voices")
        if voices:
            print(f"  Sample voices: {voices[:3]}")
        
        # Test synthesis (if voices available)
        if voices:
            test_voice = voices[0]
            test_text = "Hello, this is a test from Windows TTS."
            output_file = Path("test_windows_output.mp3")
            
            print(f"\nTesting synthesis with voice: {test_voice}")
            success = await engine.synthesize(test_text, test_voice, output_file)
            
            if success and output_file.exists():
                file_size = output_file.stat().st_size
                print(f"✓ Synthesis successful! Generated {file_size} byte MP3 file")
                output_file.unlink()  # Clean up test file
                return True
            else:
                print("✗ Synthesis failed")
                return False
        else:
            print("No voices available for testing")
            return False
            
    except Exception as e:
        print(f"✗ Error testing Windows engine: {e}")
        return False

async def test_tts_manager_integration():
    """Test Windows provider through TTSManager"""
    print("\nTesting TTSManager integration...")
    
    try:
        manager = TTSManager()
        providers = manager.get_available_providers()
        
        print(f"Available providers: {list(providers.keys())}")
        
        if 'windows' in providers:
            print("✓ Windows provider is available in TTSManager")
            
            windows_voices = manager.get_provider_voices('windows')
            print(f"✓ Windows voices through manager: {len(windows_voices)}")
            
            if windows_voices:
                test_voice = windows_voices[0]
                test_text = "Testing Windows TTS through TTSManager."
                output_file = Path("test_manager_windows.mp3")
                
                print(f"Testing synthesis through manager with voice: {test_voice}")
                success = await manager.synthesize(test_text, 'windows', test_voice, output_file)
                
                if success and output_file.exists():
                    file_size = output_file.stat().st_size
                    print(f"✓ Manager synthesis successful! Generated {file_size} byte MP3 file")
                    output_file.unlink()  # Clean up test file
                    return True
                else:
                    print("✗ Manager synthesis failed")
                    return False
            else:
                print("No Windows voices available through manager")
                return False
        else:
            print("✗ Windows provider not available in TTSManager")
            return False
            
    except Exception as e:
        print(f"✗ Error testing TTSManager integration: {e}")
        return False

async def main():
    """Run all tests"""
    print("Windows TTS Integration Test")
    print("=" * 40)
    
    # Check if Windows TTS is enabled in config
    if not WINDOWS_TTS_ENABLED:
        print("⚠️  WARNING: WINDOWS_TTS_ENABLED = False in config.py")
        print("   Set WINDOWS_TTS_ENABLED = True to enable Windows TTS integration")
        print("   Some tests may fail without this setting.\n")
    
    tests = [
        ("Windows Service Health", test_windows_service_health),
        ("Windows Service Providers", test_windows_service_providers),
        ("Windows Engine", test_windows_engine),
        ("TTSManager Integration", test_tts_manager_integration),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"\n{'='*20} {test_name} {'='*20}")
        
        if asyncio.iscoroutinefunction(test_func):
            result = await test_func()
        else:
            result = test_func()
            
        results.append((test_name, result))
    
    # Summary
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")
    
    passed = 0
    for test_name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"{test_name:30} {status}")
        if result:
            passed += 1
    
    print(f"\nPassed: {passed}/{len(results)} tests")
    
    if passed == len(results):
        print("🎉 All tests passed! Windows TTS integration is working.")
    else:
        print("❌ Some tests failed. Check Windows service and configuration.")

if __name__ == "__main__":
    asyncio.run(main())