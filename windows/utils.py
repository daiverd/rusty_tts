# -*- coding: utf-8 -*-
"""
Shared utilities for Windows TTS service
Python 2.7 Compatible
"""

import subprocess

# Python 2.7 compatibility layer
try:
    unicode
except NameError:
    # Python 3
    unicode = str
    basestring = str

def safe_split_lines(text):
    """Safely split text into lines, handling mixed Windows/Unix line endings"""
    if not text:
        return []
    # Remove all \r characters, then split on \n
    # This handles \r\n (Windows), \n (Unix), \r (old Mac), and mixed scenarios
    return text.replace('\r', '').split('\n')

def safe_subprocess_output(cmd, **kwargs):
    """Safely execute subprocess and decode output with fallback encoding"""
    try:
        result = subprocess.check_output(cmd, stderr=subprocess.STDOUT, **kwargs)
        # Try UTF-8 first
        try:
            return result.decode('utf-8')
        except UnicodeDecodeError:
            # Fallback to Windows CP1252
            try:
                return result.decode('cp1252')
            except UnicodeDecodeError:
                # Final fallback to ASCII with replacement
                return result.decode('ascii', 'replace')
    except subprocess.CalledProcessError as e:
        # Handle command errors gracefully
        if hasattr(e, 'output') and e.output:
            try:
                return e.output.decode('utf-8', 'replace')
            except:
                return str(e)
        raise

def safe_encode_for_subprocess(text):
    """Safely encode text for subprocess arguments"""
    if isinstance(text, unicode):
        return text.encode('utf-8')
    elif isinstance(text, str):
        # Assume it's already bytes or try to decode/encode
        try:
            return text.decode('utf-8').encode('utf-8')
        except UnicodeDecodeError:
            return text.decode('cp1252', 'replace').encode('utf-8')
    else:
        return str(text).encode('utf-8')

def clean_unicode_for_json(obj):
    """Recursively clean unicode issues in data structures for JSON serialization"""
    if isinstance(obj, dict):
        # Use explicit loop for Python 2.7 compatibility
        result = {}
        for k, v in obj.items():
            result[k] = clean_unicode_for_json(v)
        return result
    elif isinstance(obj, list):
        return [clean_unicode_for_json(item) for item in obj]
    elif isinstance(obj, unicode):
        # Ensure unicode strings are properly handled
        try:
            return obj.encode('utf-8', 'replace').decode('utf-8', 'replace')
        except:
            return obj.encode('ascii', 'replace').decode('ascii', 'replace')
    elif isinstance(obj, str):
        # Handle byte strings
        try:
            return obj.decode('utf-8', 'replace')
        except UnicodeDecodeError:
            try:
                return obj.decode('cp1252', 'replace')
            except UnicodeDecodeError:
                return obj.decode('ascii', 'replace')
    else:
        return obj