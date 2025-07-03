# -*- coding: utf-8 -*-
"""
Test script for Unicode safety in Windows TTS service
"""

import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Test the unicode utility functions
from utils import safe_subprocess_output, safe_encode_for_subprocess, clean_unicode_for_json, safe_split_lines
from app import safe_jsonify

def test_safe_encode_for_subprocess():
    """Test safe encoding for subprocess arguments"""
    print("Testing safe_encode_for_subprocess...")
    
    # Test cases
    test_cases = [
        u"Hello World",  # Basic ASCII
        u"Hëllö Wørld",  # Latin characters with accents
        u"你好世界",      # Chinese characters
        u"Здравствуй мир", # Cyrillic
        "Mixed: Café ñoño",  # Mixed encoding
        "",  # Empty string
        None,  # None value
    ]
    
    for i, test_case in enumerate(test_cases):
        try:
            if test_case is not None:
                result = safe_encode_for_subprocess(test_case)
                # Use % formatting for Python 2.7 compatibility
                print("  Test %d: '%s' -> %d bytes" % (i+1, repr(test_case), len(result)))
            else:
                result = safe_encode_for_subprocess(test_case)
                print("  Test %d: None -> %d bytes" % (i+1, len(result)))
        except Exception as e:
            print("  Test %d: ERROR - %s" % (i+1, e))

def test_clean_unicode_for_json():
    """Test unicode cleaning for JSON serialization"""
    print("\nTesting clean_unicode_for_json...")
    
    test_data = {
        'ascii_text': 'Hello World',
        'unicode_text': u'Hëllö Wørld',
        'mixed_list': [u'Café', 'regular', u'ñoño'],
        'nested': {
            'voice_name': u'Microsoft María',
            'description': u'Voz femenina en español'
        },
        'number': 42,
        'boolean': True
    }
    
    try:
        cleaned = clean_unicode_for_json(test_data)
        print("  Original keys:", test_data.keys())
        print("  Cleaned keys:", cleaned.keys())
        print("  Unicode text cleaned:", repr(cleaned.get('unicode_text')))
        print("  Nested voice name:", repr(cleaned['nested']['voice_name']))
    except Exception as e:
        print("  ERROR:", e)

def test_mock_balcon_output():
    """Test handling of mock balcon-like output with unicode"""
    print("\nTesting mock balcon output parsing...")
    
    # Simulate balcon -l output with unicode voice names
    mock_output = u"""SAPI 4:
  Alex :: Adult Male #8, American English (TruVoice)
  María :: Voz femenina, Español (TruVoice)

SAPI 5:
  Microsoft Sam
  Microsoft María
  Microsoft Hedda
  Vocalizer Expressive Ángela"""
    
    try:
        # Test our parsing logic similar to providers() endpoint
        voices = []
        current_sapi = None
        
        # Handle mixed line endings safely
        lines = safe_split_lines(mock_output)
        for line in lines:
            if not line.strip():
                continue
                
            if line.startswith('SAPI 4:'):
                current_sapi = 4
                continue
            elif line.startswith('SAPI 5:'):
                current_sapi = 5
                continue
            
            if not line.startswith('  ') or current_sapi is None:
                continue
            
            line = line[2:].strip()
            if not line:
                continue
            
            if current_sapi == 4:
                if '::' in line:
                    voice_name = line.split('::')[0].strip()
                    description = line.split('::')[1].strip()
                    voices.append({
                        'name': voice_name,
                        'sapi_version': 4,
                        'description': description
                    })
            elif current_sapi == 5:
                voice_name = line.strip()
                voices.append({
                    'name': voice_name,
                    'sapi_version': 5,
                    'description': ''
                })
        
        print("  Parsed %d voices successfully" % len(voices))
        for voice in voices:
            print("    %s: %s (SAPI %d)" % (
                repr(voice['name']), 
                repr(voice.get('description', '')), 
                voice['sapi_version']
            ))
            
        # Test JSON serialization of the result
        cleaned_voices = clean_unicode_for_json(voices)
        print("  JSON serialization test passed")
        
    except Exception as e:
        print("  ERROR:", e)

def test_line_ending_handling():
    """Test handling of mixed line endings from balcon output"""
    print("\nTesting line ending handling...")
    
    # Test different line ending scenarios
    test_cases = [
        ("Windows CRLF", "SAPI 4:\r\n  Microsoft Sam\r\n  Microsoft Mary\r\n"),
        ("Unix LF", "SAPI 4:\n  Microsoft Sam\n  Microsoft Mary\n"),
        ("Old Mac CR", "SAPI 4:\r  Microsoft Sam\r  Microsoft Mary\r"),
        ("Mixed", "SAPI 4:\r\n  Microsoft Sam\n  Microsoft Mary\r"),
        ("Leading newline", "\nSAPI 4:\r\n  Microsoft Sam\r\n"),
        ("Trailing newlines", "SAPI 4:\r\n  Microsoft Sam\r\n\r\n"),
    ]
    
    for name, test_input in test_cases:
        try:
            lines = safe_split_lines(test_input)
            non_empty_lines = [line for line in lines if line.strip()]
            print("  %s: %d lines parsed" % (name, len(non_empty_lines)))
            
            # Verify we can parse the structure
            sapi_found = False
            voice_count = 0
            for line in lines:
                if line.strip().startswith('SAPI 4:'):
                    sapi_found = True
                elif line.startswith('  ') and line.strip():
                    voice_count += 1
            
            if sapi_found and voice_count > 0:
                print("    Parsing successful: SAPI section found, %d voices" % voice_count)
            else:
                print("    Parsing failed: SAPI=%s, voices=%d" % (sapi_found, voice_count))
                
        except Exception as e:
            print("  %s: ERROR - %s" % (name, e))

def test_command_line_encoding():
    """Test command line argument encoding"""
    print("\nTesting command line encoding...")
    
    test_texts = [
        u"Hello World",
        u"Café con leche", 
        u"Здравствуй",
        u"测试"
    ]
    
    test_voices = [
        u"Microsoft Sam",
        u"Microsoft María", 
        u"Vocalizer Ángela"
    ]
    
    for text in test_texts:
        for voice in test_voices:
            try:
                text_encoded = safe_encode_for_subprocess(text)
                voice_encoded = safe_encode_for_subprocess(voice)
                
                # Simulate command construction
                cmd = [
                    'balcon.exe',
                    '-t', text_encoded,
                    '-n', voice_encoded
                ]
                
                print("  Command for '%s' + '%s': OK" % (
                    repr(text)[:20], repr(voice)[:15]
                ))
                
            except Exception as e:
                print("  Command for '%s' + '%s': ERROR - %s" % (
                    repr(text)[:20], repr(voice)[:15], e
                ))

if __name__ == '__main__':
    print("Unicode Safety Test for Windows TTS Service")
    print("=" * 50)
    
    test_safe_encode_for_subprocess()
    test_clean_unicode_for_json()
    test_mock_balcon_output()
    test_line_ending_handling()
    test_command_line_encoding()
    
    print("\n" + "=" * 50)
    print("Test completed. Check output above for any ERRORs.")