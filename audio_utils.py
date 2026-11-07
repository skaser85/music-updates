import re
import time
import requests
from pathlib import Path
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
from mutagen import File as MutagenFile

DURATION_LIMIT_SECONDS = 1500 

WIKI_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 MusicOrganizerBot/1.0 (contact: skaser85@gmail.com)',
    'Accept': 'application/json',
    'Accept-Language': 'en-US,en;q=0.9',
    'Connection': 'keep-alive'
}

def extract_clean_string(tag_data, fallback_value=""):
    """Safely extracts strings from Mutagen elements and strips bracket artifacts."""
    if not tag_data:
        return fallback_value
        
    if isinstance(tag_data, (list, tuple)) or (hasattr(tag_data, '__iter__') and not isinstance(tag_data, str)):
        val = str(tag_data).strip() if len(tag_data) > 0 else fallback_value
    else:
        val = str(tag_data).strip()
        
    if val.startswith("['") and val.endswith("']"): val = val[2:-2]
    elif val.startswith('["') and val.endswith('"]'): val = val[2:-2]
    elif val.startswith('[') and val.endswith(']'): val = val[1:-1]
        
    return val.strip() if val else fallback_value

def clean_track_title(title_string):
    """
    Advanced filter that strips out box set notations, disk indices, 
    track numbers, hyphens, and structural whitespace from the start of a title.
    """
    cleaned = title_string.strip()
    cleaned = re.sub(r'^\[\d+[\s\-_]*\d*\]\s*', '', cleaned)
    cleaned = re.sub(r'^[\d\s\.\-_]+', '', cleaned)
    return cleaned.strip()

def clean_metadata_text(text_value, field_type="album"):
    """
    Detects if raw metadata tags contain web URLs or placeholder text patterns
    and substitutes them with clean, readable group descriptions.
    """
    text_clean = text_value.strip()
    
    # Check if the string matches a web URL structure (contains http, https, or .org/.com style domains)
    if re.search(r'(https?://|www\.)', text_clean, re.IGNORECASE) or text_clean.lower().endswith('.org') or text_clean.lower().endswith('.com'):
        # Specific override for your OverClocked ReMix files
        if "ocremix" in text_clean.lower():
            return "Overclocked Remix"
        return f"Unknown {field_type.title()}"
        
    return text_clean

def fetch_wikipedia_album_art(artist, album):
    """Queries Wikipedia using Exponential Backoff and strong browser emulation headers."""
    if artist == "Unknown Artist" or album == "Unknown Album":
        return "Skipped (Missing Metadata)", ""

    clean_album = album.replace('[', '').replace(']', '')
    search_query = f"{clean_album} {artist} album"
    search_url = "https://wikipedia.org"
    search_params = {"action": "query", "list": "search", "srsearch": search_query, "format": "json", "srlimit": 1}
    
    time.sleep(0.3) 
    retries, backoff_delay = 3, 3
    
    for attempt in range(retries):
        try:
            response = requests.get(search_url, headers=WIKI_HEADERS, params=search_params, timeout=7)
            if response.status_code == 429:
                time.sleep(backoff_delay)
                backoff_delay *= 2
                continue
                
            if response.status_code != 200:
                return f"HTTP Error ({response.status_code})", ""
            
            search_data = response.json()
            search_results = search_data.get("query", {}).get("search", [])
            if not search_results:
                return "No Album Page Found", ""
                
            page_title = search_results["title"]
            
            image_params = {"action": "query", "titles": page_title, "prop": "pageimages", "format": "json", "pithumbsize": 600, "pilicense": "any"}
            img_response = requests.get(search_url, headers=WIKI_HEADERS, params=image_params, timeout=7)
            
            if img_response.status_code == 429:
                time.sleep(backoff_delay)
                backoff_delay *= 2
                continue
                
            img_data = img_response.json()
            pages = img_data.get("query", {}).get("pages", {})
            for _, page_info in pages.items():
                if "thumbnail" in page_info:
                    return f"Found via: '{page_title}'", page_info["thumbnail"]["source"]
                    
            return f"Article Found ('{page_title}'), but no cover image available", ""
        except Exception as e:
            if attempt == retries - 1:
                return f"Error ({type(e).__name__})", ""
            time.sleep(backoff_delay)
            backoff_delay *= 2
            
    return "Skipped: Persistent WAF/Rate Block", ""

def check_album_art(file_path, extension):
    """Checks audio container properties for pre-existing embedded artwork."""
    try:
        if extension == '.mp3':
            audio = MP3(file_path)
            return "YES" if audio and any(k.startswith('APIC') for k in audio.keys()) else "No"
        audio = MutagenFile(file_path)
        if audio is None: return "No"
        if extension == '.flac' and hasattr(audio, 'pictures') and audio.pictures: return "YES"
        if extension == '.m4a' and 'covr' in audio: return "YES"
        return "YES" if any(x in k.lower() for k in audio.keys() for x in ['covr', 'art', 'pic']) else "No"
    except Exception:
        return "No"

def analyze_for_podcast(file_path, extension):
    """Flags long durations or application meta frames indicating a podcast."""
    try:
        audio_file = MutagenFile(file_path)
        if audio_file and audio_file.info and audio_file.info.length > DURATION_LIMIT_SECONDS:
            return True, f"Long Duration ({int(audio_file.info.length // 60)} mins)"
    except Exception:
        pass
    if extension == '.mp3':
        try:
            mp3_audio = MP3(file_path)
            if 'PCST' in mp3_audio or 'WFED' in mp3_audio: return True, "ID3 Podcast Flags"
        except Exception:
            pass
    return False, ""

def clean_filename_string(text):
    """Ensures values remain legal when mapping properties to Linux filenames."""
    text = text.replace('/', '-')
    return re.sub(r'[\"\*\?<>\|]', '', text).strip()

