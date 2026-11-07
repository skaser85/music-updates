import csv
import os
import re
import time
import requests
from pathlib import Path
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
from mutagen import File as MutagenFile

# --- CONFIGURATION ---
MUSIC_DIR = "/media/steve/New Volume/Music/Music1" 
OUTPUT_CSV = "proposed_music_changes.csv"
TRACK_LIMIT = 500  
DURATION_LIMIT_SECONDS = 1500 

WIKI_HEADERS = {
    'User-Agent': 'MusicLibraryOrganizerBot/1.0 (contact: your_email@example.com)'
}

def extract_clean_string(tag_data, fallback_value=""):
    """
    Unwraps Mutagen tag data. If it's a list/array, takes the first element.
    Strips out bracket and quote artifacts.
    """
    if not tag_data:
        return fallback_value
    
    # If it's a list, tuple, or Mutagen wrapper, pull the first value safely
    if isinstance(tag_data, (list, tuple)) or hasattr(tag_data, '__iter__') and not isinstance(tag_data, str):
        if len(tag_data) > 0:
            val = str(tag_data[0]).strip()
        else:
            return fallback_value
    else:
        val = str(tag_data).strip()
        
    return val if val else fallback_value

def fetch_wikipedia_album_art(artist, album):
    """Queries the Wikipedia API safely to find the main album image."""
    if artist == "Unknown Artist" or album == "Unknown Album":
        return "Skipped (Missing Metadata)", ""

    search_query = f"{album} {artist} album"
    search_url = "https://en.wikipedia.org/w/api.php"
    
    search_params = {
        "action": "query",
        "list": "search",
        "srsearch": search_query,
        "format": "json",
        "srlimit": 1
    }
    
    try:
        time.sleep(0.1) # Safe execution delay
        response = requests.get(search_url, headers=WIKI_HEADERS, params=search_params, timeout=5)
        
        if response.status_code != 200:
            return f"HTTP Error ({response.status_code})", ""
            
        # Safer JSON evaluation check
        try:
            search_data = response.json()
        except ValueError:
            return "API Error: Non-JSON payload received", ""
            
        search_results = search_data.get("query", {}).get("search", [])
        if not search_results:
            return "No Article Found", ""
            
        page_title = search_results[0]["title"] # Safely pull first element index
        
        image_params = {
            "action": "query",
            "titles": page_title,
            "prop": "pageimages",
            "format": "json",
            "pithumbsize": 600,
            "pilicense": "any"
        }
        
        img_response = requests.get(search_url, headers=WIKI_HEADERS, params=image_params, timeout=5)
        
        if img_response.status_code != 200:
            return f"HTTP Error on Image Lookup ({img_response.status_code})", ""
            
        try:
            img_data = img_response.json()
        except ValueError:
            return "API Error: Image metadata not valid JSON", ""
            
        pages = img_data.get("query", {}).get("pages", {})
        for page_id, page_info in pages.items():
            if "thumbnail" in page_info:
                img_url = page_info["thumbnail"]["source"]
                return f"Found via: '{page_title}'", img_url
                
        return f"Article Found ('{page_title}'), but no cover image available", ""
        
    except requests.exceptions.RequestException as e:
        return f"Network Error: {type(e).__name__}", ""

def check_album_art(file_path, extension):
    """Checks if an audio file contains embedded album art."""
    try:
        if extension == '.mp3':
            audio = MP3(file_path)
            if audio and any(key.startswith('APIC') for key in audio.keys()):
                return "YES"
        else:
            audio = MutagenFile(file_path)
            if audio is None:
                return "No"
            if extension == '.flac' and hasattr(audio, 'pictures') and audio.pictures:
                return "YES"
            if extension == '.m4a' and 'covr' in audio:
                return "YES"
            for key in audio.keys():
                if 'covr' in key.lower() or 'art' in key.lower() or 'pic' in key.lower():
                    return "YES"
    except Exception:
        pass
    return "No"

def analyze_for_podcast(file_path, extension):
    """Analyzes an audio file to determine if it is a podcast."""
    try:
        audio_file = MutagenFile(file_path)
        if audio_file and audio_file.info:
            if audio_file.info.length > DURATION_LIMIT_SECONDS:
                return True, f"Long Duration ({int(audio_file.info.length // 60)} mins)"
    except Exception:
        pass

    if extension == '.mp3':
        try:
            mp3_audio = MP3(file_path)
            if 'PCST' in mp3_audio or 'WFED' in mp3_audio:
                return True, "ID3 Podcast Flags"
        except Exception:
            pass
    return False, ""

def clean_filename_string(text):
    text = text.replace('/', '-')
    text = re.sub(r'[\"\*\?<>\|]', '', text)
    return text.strip()

def get_audio_info(file_path, base_dir):
    path = Path(file_path)
    extension = path.suffix.lower()
    base_path = Path(base_dir)
    
    try:
        rel_current_path = path.relative_to(base_path)
    except ValueError:
        rel_current_path = path
        
    raw_title, raw_artist, raw_album, raw_track = "", "", "", ""
    
    try:
        is_mp3 = (extension == '.mp3')
        audio = EasyID3(file_path) if is_mp3 else MutagenFile(file_path)
        if audio:
            raw_title = extract_clean_string(audio.get('title', ''))
            raw_artist = extract_clean_string(audio.get('artist', ''))
            raw_album = extract_clean_string(audio.get('album', ''))
            raw_track = extract_clean_string(audio.get('tracknumber', ''))
    except Exception:
        pass

    is_podcast, podcast_reason = analyze_for_podcast(file_path, extension)
    has_art = check_album_art(file_path, extension)

    # If title tag is empty, unwrap and parse the fallback filename stem
    if not raw_title.strip():
        processed_title = path.stem.replace('_', ' ').replace('-', ' ').strip().title()
    else:
        processed_title = raw_title.title()
        
    proposed_artist = raw_artist.title() if raw_artist.strip() else "Unknown Artist"
    proposed_album = raw_album.title() if raw_album.strip() else "Unknown Album"
    
    proposed_track = ""
    if raw_track.strip():
        track_match = re.match(r'^(\d+)', raw_track.strip())
        if track_match:
            proposed_track = f"{int(track_match.group(1)):02d} "

    safe_artist = clean_filename_string(proposed_artist)
    safe_album = clean_filename_string(proposed_album)
    safe_title = clean_filename_string(processed_title)
    proposed_filename = f"{proposed_track}{safe_title}.mp3"
    
    rel_proposed_path = Path(safe_artist) / safe_album / proposed_filename

    if is_podcast:
        proposed_action = "Skip (Podcast Detected)"
        rel_proposed_path = "N/A - Skipped"
        wiki_status, wiki_url = "Skipped (Podcast)", ""
    else:
        proposed_action = "Convert to MP3 & Move" if extension != '.mp3' else "Move/Rename & Update Tags"
        
        if has_art == "No":
            wiki_status, wiki_url = fetch_wikipedia_album_art(proposed_artist, proposed_album)
        else:
            wiki_status, wiki_url = "Skipped (Art Natively Present)", ""

    return {
        "Relative File Path": str(rel_current_path),
        "Current Extension": extension,
        "Is Podcast": "YES" if is_podcast else "No",
        "Has Album Art": has_art,
        "Wikipedia Art Status": wiki_status,
        "Simulated Art URL": wiki_url,
        "Proposed Action": proposed_action,
        "Proposed Title": processed_title,
        "Proposed Artist": proposed_artist,
        "Proposed Album": proposed_album,
        "Proposed New Path": str(rel_proposed_path)
    }

def generate_report(directory, output_csv):
    path = Path(directory)
    supported_extensions = {'.mp3', '.wav', '.flac', '.m4a', '.ogg', '.wma'}
    
    headers = [
        "Relative File Path", "Current Extension", "Is Podcast", "Has Album Art", 
        "Wikipedia Art Status", "Simulated Art URL", "Proposed Action", 
        "Proposed Title", "Proposed Artist", "Proposed Album", "Proposed New Path"
    ]
    
    print(f"🚀 Initializing test execution for up to {TRACK_LIMIT} elements...")
    count = 0
    
    with open(output_csv, mode='w', newline='', encoding='utf-8') as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=headers)
        writer.writeheader()
        
        for file_path in path.rglob('*'):
            if count >= TRACK_LIMIT:
                print(f"🛑 Reached sample threshold of {TRACK_LIMIT}. Ending scan cycle.")
                break
                
            if file_path.is_file() and file_path.suffix.lower() in supported_extensions:
                row_data = get_audio_info(file_path, directory)
                writer.writerow(row_data)
                count += 1
                
                if count % 100 == 0:
                    print(f"   Progress Tracker: Evaluated {count}/{TRACK_LIMIT} targets...")
                
    print(f"📊 Completed! Output saved smoothly to: {output_csv}")

if __name__ == "__main__":
    if os.path.exists(MUSIC_DIR):
        generate_report(MUSIC_DIR, OUTPUT_CSV)
    else:
        print(f"❌ Error: Target root directory context configuration invalid.")

