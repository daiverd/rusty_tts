import requests
import random
import time

def get_random_commons_audio_v1():
    """
    Method 1: Use the API:Random module with namespace 6 (File namespace)
    This gets truly random files from Commons, then filters for audio
    """
    api_url = "https://commons.wikimedia.org/w/api.php"
    
    max_attempts = 20  # Try up to 20 random files to find an audio file
    
    for attempt in range(max_attempts):
        params = {
            'action': 'query',
            'format': 'json',
            'list': 'random',
            'rnnamespace': 6,  # File namespace
            'rnlimit': 10,     # Get 10 random files at once
        }
        
        try:
            response = requests.get(api_url, params=params)
            response.raise_for_status()
            data = response.json()
            
            random_files = data.get('query', {}).get('random', [])
            
            # Filter for audio files
            audio_extensions = ['.ogg', '.oga', '.wav', '.mp3', '.flac', '.m4a', '.opus']
            audio_files = [
                f for f in random_files 
                if any(f['title'].lower().endswith(ext) for ext in audio_extensions)
            ]
            
            if audio_files:
                # Pick a random audio file from the filtered results
                selected_file = random.choice(audio_files)
                file_info = get_file_info(selected_file['title'])
                
                if file_info and file_info['url']:
                    return {
                        'title': selected_file['title'],
                        'url': file_info['url'],
                        'commons_page': f"https://commons.wikimedia.org/wiki/{selected_file['title'].replace(' ', '_')}",
                        'duration': file_info['duration'],
                        'duration_formatted': format_duration(file_info['duration']),
                        'size': file_info['size'],
                        'mime_type': file_info['mime'],
                        'method': 'random_api'
                    }
                else:
                    # Fallback to basic info if detailed info fails
                    return {
                        'title': selected_file['title'],
                        'url': None,
                        'commons_page': f"https://commons.wikimedia.org/wiki/{selected_file['title'].replace(' ', '_')}",
                        'duration': None,
                        'duration_formatted': "Unknown",
                        'method': 'random_api'
                    }
            
            # Small delay to avoid hitting API too hard
            time.sleep(0.1)
            
        except requests.RequestException as e:
            print(f"Error in attempt {attempt + 1}: {e}")
            continue
    
    return None

def get_random_commons_audio_v2():
    """
    Method 2: Use allimages with alphabetical random starting point
    Pick a random letter/prefix to start from, then find audio files
    """
    api_url = "https://commons.wikimedia.org/w/api.php"
    
    # Generate random starting points (letters, numbers, common prefixes)
    import string
    random_starts = (
        list(string.ascii_uppercase) + 
        list(string.digits) + 
        ['Audio', 'Music', 'Sound', 'Record', 'Voice', 'Song', 'Speech']
    )
    
    # Try several random starting points
    for _ in range(5):
        try:
            random_start = random.choice(random_starts)
            
            params = {
                'action': 'query',
                'format': 'json',
                'list': 'allimages',
                'aifrom': random_start,
                'aisort': 'name',
                'ailimit': 100,
                'aiprop': 'url|mime|timestamp'
            }
            
            response = requests.get(api_url, params=params)
            response.raise_for_status()
            data = response.json()
            
            files = data.get('query', {}).get('allimages', [])
            
            # Filter for audio files by extension and MIME type
            audio_extensions = ['.ogg', '.oga', '.wav', '.mp3', '.flac', '.m4a', '.opus']
            audio_mimes = ['audio/ogg', 'audio/mpeg', 'audio/wav', 'audio/flac', 'application/ogg']
            
            audio_files = []
            for f in files:
                # Check by extension
                is_audio_ext = any(f['name'].lower().endswith(ext) for ext in audio_extensions)
                # Check by MIME type if available
                is_audio_mime = f.get('mime', '').startswith('audio/') or f.get('mime') in audio_mimes
                
                if is_audio_ext or is_audio_mime:
                    audio_files.append(f)
            
            if audio_files:
                selected_file = random.choice(audio_files)
                return {
                    'title': f"File:{selected_file['name']}",
                    'url': selected_file['url'],
                    'commons_page': f"https://commons.wikimedia.org/wiki/File:{selected_file['name'].replace(' ', '_')}",
                    'mime_type': selected_file.get('mime'),
                    'method': 'allimages_alphabetical_random'
                }
                
        except requests.RequestException as e:
            print(f"Error with starting point {random_start}: {e}")
            continue
    
    return None

def get_random_commons_audio_v3():
    """
    Method 3: Use category-based approach with random offset
    More reliable but limited to categorized files
    """
    api_url = "https://commons.wikimedia.org/w/api.php"
    
    # Audio categories that typically have many files
    audio_categories = [
        'Category:Audio files',
        'Category:Ogg files',
        'Category:Music',
        'Category:Spoken Wikipedia',
        'Category:Sound effects'
    ]
    
    for category in audio_categories:
        try:
            # First, get the total count (approximately)
            params = {
                'action': 'query',
                'format': 'json',
                'list': 'categorymembers',
                'cmtitle': category,
                'cmtype': 'file',
                'cmlimit': 500  # Max limit to get a sense of size
            }
            
            response = requests.get(api_url, params=params)
            response.raise_for_status()
            data = response.json()
            
            members = data.get('query', {}).get('categorymembers', [])
            if not members:
                continue
            
            # If we got 500 results, there are likely more
            # Use continuation to jump to a random point
            if len(members) == 500 and 'continue' in data:
                # Generate a random continuation point
                # This is a bit hacky but works for getting varied results
                random_offset = random.randint(0, 50)  # Skip some pages
                
                for _ in range(random_offset):
                    if 'continue' not in data:
                        break
                    
                    continue_params = params.copy()
                    continue_params.update(data['continue'])
                    
                    response = requests.get(api_url, params=continue_params)
                    response.raise_for_status()
                    data = response.json()
                    
                    if not data.get('query', {}).get('categorymembers'):
                        break
            
            # Get current page of results
            final_members = data.get('query', {}).get('categorymembers', [])
            if final_members:
                # Filter for audio file extensions
                audio_extensions = ['.ogg', '.oga', '.wav', '.mp3', '.flac', '.m4a', '.opus']
                audio_files = [
                    f for f in final_members 
                    if any(f['title'].lower().endswith(ext) for ext in audio_extensions)
                ]
                
                if audio_files:
                    selected_file = random.choice(audio_files)
                    file_info = get_file_info(selected_file['title'])
                    
                    if file_info and file_info['url']:
                        return {
                            'title': selected_file['title'],
                            'url': file_info['url'],
                            'commons_page': f"https://commons.wikimedia.org/wiki/{selected_file['title'].replace(' ', '_')}",
                            'duration': file_info['duration'],
                            'duration_formatted': format_duration(file_info['duration']),
                            'size': file_info['size'],
                            'mime_type': file_info['mime'],
                            'category': category,
                            'method': 'category_random_offset'
                        }
            
        except requests.RequestException as e:
            print(f"Error with category {category}: {e}")
            continue
    
    return None

def get_file_info(file_title):
    """
    Get the direct URL and metadata (including duration) for a file given its title
    """
    api_url = "https://commons.wikimedia.org/w/api.php"
    
    params = {
        'action': 'query',
        'format': 'json',
        'titles': file_title,
        'prop': 'imageinfo',
        'iiprop': 'url|size|dimensions|metadata|mime'
    }
    
    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        data = response.json()
        
        pages = data.get('query', {}).get('pages', {})
        for page_id, page_data in pages.items():
            if 'imageinfo' in page_data and page_data['imageinfo']:
                info = page_data['imageinfo'][0]
                
                # Extract duration from metadata
                duration = extract_duration_from_metadata(info.get('metadata', []), info.get('mime', ''))
                
                return {
                    'url': info.get('url'),
                    'size': info.get('size'),  # File size in bytes
                    'mime': info.get('mime'),
                    'duration': duration,
                    'width': info.get('width'),
                    'height': info.get('height')
                }
        
        return None
        
    except requests.RequestException as e:
        print(f"Error getting file info: {e}")
        return None

def extract_duration_from_metadata(metadata, mime_type):
    """
    Extract duration from file metadata.
    Different formats store duration in different fields.
    """
    if not metadata:
        return None
    
    # Convert metadata list to dict for easier access
    metadata_dict = {}
    for item in metadata:
        if isinstance(item, dict) and 'name' in item and 'value' in item:
            metadata_dict[item['name']] = item['value']
    
    # Debug: Print available metadata fields (uncomment for debugging)
    # print(f"Available metadata fields: {list(metadata_dict.keys())}")
    
    # Try different duration fields based on format
    duration_fields = [
        'playtime_seconds',    # WebM, MP4
        'length',              # Ogg
        'duration',            # General
        'playtime_string',     # Sometimes available as string
        'length_seconds',      # Alternative
        'DURATION',            # EXIF style
        'totalsampleframes',   # Sometimes we need to calculate from this
        'samples',             # Alternative sample count
    ]
    
    for field in duration_fields:
        if field in metadata_dict:
            try:
                duration_value = metadata_dict[field]
                
                # Handle different duration formats
                if isinstance(duration_value, (int, float)):
                    return float(duration_value)
                elif isinstance(duration_value, str):
                    # Try to parse string duration (e.g., "123.45" or "02:03.45")
                    if ':' in duration_value:
                        # Handle MM:SS.ss or HH:MM:SS format
                        parts = duration_value.split(':')
                        if len(parts) == 2:  # MM:SS
                            minutes, seconds = parts
                            return float(minutes) * 60 + float(seconds)
                        elif len(parts) == 3:  # HH:MM:SS
                            hours, minutes, seconds = parts
                            return float(hours) * 3600 + float(minutes) * 60 + float(seconds)
                    else:
                        # Try direct float conversion
                        return float(duration_value)
            except (ValueError, TypeError):
                continue
    
    # Try to calculate duration from sample rate and sample count
    if 'totalsampleframes' in metadata_dict and 'samplerate' in metadata_dict:
        try:
            samples = float(metadata_dict['totalsampleframes'])
            sample_rate = float(metadata_dict['samplerate'])
            if sample_rate > 0:
                return samples / sample_rate
        except (ValueError, TypeError):
            pass
    
    return None

def format_duration(seconds):
    """
    Format duration in seconds to a human-readable string
    """
    if seconds is None:
        return "Unknown"
    
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        remaining_seconds = seconds % 60
        return f"{minutes}m {remaining_seconds:.1f}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        remaining_seconds = seconds % 60
        return f"{hours}h {minutes}m {remaining_seconds:.1f}s"

def get_random_commons_audio(method='auto'):
    """
    Get a random audio file from Wikimedia Commons using various methods
    
    Args:
        method: 'auto', 'random_api', 'allimages', 'category', or 'all'
    """
    methods = {
        'random_api': get_random_commons_audio_v1,
        'allimages': get_random_commons_audio_v2,
        'category': get_random_commons_audio_v3
    }
    
    if method == 'auto' or method == 'all':
        # Try methods in order of preference
        method_order = ['random_api', 'category', 'allimages']
        if method == 'all':
            # Try all methods and return the first successful one
            for method_name in method_order:
                print(f"Trying method: {method_name}")
                result = methods[method_name]()
                if result:
                    return result
        else:
            # Try random_api first, then category (more reliable), then allimages
            for method_name in method_order:
                result = methods[method_name]()
                if result:
                    return result
    elif method in methods:
        return methods[method]()
    else:
        raise ValueError(f"Unknown method: {method}. Use 'auto', 'random_api', 'allimages', 'category', or 'all'")
    
    return None

def debug_file_metadata(file_title):
    """
    Debug function to see what metadata is available for a file
    """
    api_url = "https://commons.wikimedia.org/w/api.php"
    
    params = {
        'action': 'query',
        'format': 'json',
        'titles': file_title,
        'prop': 'imageinfo',
        'iiprop': 'url|size|dimensions|metadata|mime'
    }
    
    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        data = response.json()
        
        pages = data.get('query', {}).get('pages', {})
        for page_id, page_data in pages.items():
            if 'imageinfo' in page_data and page_data['imageinfo']:
                info = page_data['imageinfo'][0]
                metadata = info.get('metadata', [])
                
                print(f"\n=== DEBUG: Metadata for {file_title} ===")
                print(f"MIME type: {info.get('mime')}")
                print(f"File size: {info.get('size')} bytes")
                print("Metadata fields:")
                
                for item in metadata:
                    if isinstance(item, dict) and 'name' in item and 'value' in item:
                        print(f"  {item['name']}: {item['value']}")
                
                print("=== END DEBUG ===\n")
                return
        
    except requests.RequestException as e:
        print(f"Error getting metadata: {e}")

# Example usage for debugging - uncomment these lines to debug specific files
# debug_file_metadata("File:LL-Q33810 (ori)-Sangram Keshari Senapati (Ssgapu22)-ଦାମର.wav")
# debug_file_metadata("File:Q&A_Copyright.ogg")
if __name__ == "__main__":
    print("Getting random Wikimedia Commons audio files using different methods...\n")
    
    # Test different methods
    methods_to_test = ['random_api', 'allimages', 'category']
    
    for method in methods_to_test:
        print(f"=== Testing method: {method} ===")
        result = get_random_commons_audio(method=method)
        
        if result:
            print(f"✅ Success!")
            print(f"Title: {result['title']}")
            print(f"Direct URL: {result['url']}")
            print(f"Commons page: {result['commons_page']}")
            if 'timestamp' in result:
                print(f"Upload time: {result['timestamp']}")
            if 'category' in result:
                print(f"Found in category: {result['category']}")
            print(f"Method used: {result['method']}")
        else:
            print("❌ Failed to get audio file")
        
        print()
    
    print("=== Using auto method (recommended) ===")
    result = get_random_commons_audio()
    if result:
        print(f"🎵 Random audio file found:")
        print(f"Title: {result['title']}")
        print(f"URL: {result['url']}")
        print(f"Commons page: {result['commons_page']}")
        if result.get('duration') is not None:
            print(f"Duration: {result['duration_formatted']} ({result['duration']:.2f} seconds)")
        if result.get('size'):
            print(f"File size: {result['size']:,} bytes ({result['size']/1024/1024:.1f} MB)")
    else:
        print("Failed to get any random audio file")
