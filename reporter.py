import csv
import os
import re
import time
import requests
from pathlib import Path
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
from mutagen import File as MutagenFile

# Define your Linux music directory here
MUSIC_DIR = "/media/steve/New Volume/Music/Music1"
OUTPUT_CSV = "proposed_music_changes.csv"

DURATION_LIMIT_SECONDS = 1500 

# Wikipedia requires a descriptive User-Agent. Update this with your info if desired.
WIKI_HEADERS = {
    'User-Agent': 'MusicLibraryOrganizerBot/1.0 (contact: your_email@example.com)'
}

def fetch_wikipedia_album_art(artist, album):
    """
    Queries the Wikipedia API to find the main image of the album page.
    Returns (status_string, image_url_or_empty).
    """
    if artist == "Unknown Artist" or album == "Unknown Album":
        return "Skipped (Missing Metadata)", ""

    # Construct a search query (e.g., "Abbey Road Beatles album")
    search_query = f"{album} {artist} album"
    
    # Step 1: Search for the most relevant Wikipedia page title
    search_url = "https://wikipedia.org"
    search_params = {
        "action": "query",
        "list": "search",
        "srsearch": search_query,
        "format": "json",
        "srlimit": 1
    }
    
    try:
        # Polite delay to prevent spamming the API
        time.sleep(0.2) 
        
        response = requests.get(search_url, headers=WIKI_HEADERS, params=search_params, timeout=5)
        if response.status_code != 200:
            return f"HTTP Error ({response.status_code})", ""
            
        search_data = response.json()
        search_results = search_data.get("query", {}).get("search", [])
        
        if not search_results:
            return "No Article Found", ""
            
        page_title = search_results[0]["title"]
        
        # Step 2: Use pageimages API to extract the primary image thumbnail from that article
        image_params = {
            "action": "query",
            "titles": page_title,
            "prop": "pageimages",
            "format": "json",
            "pithumbsize": 600,  # Standard clean size for album art
            "pilicense": "any"   # Needed to fetch copyrighted album covers
        }
        
        img_response = requests.get(search_url, headers=WIKI_HEADERS, params=image_params, timeout=5)
        img_data = img_response.json()
        
        pages = img_data.get("query", {}).get("pages", {})
        for page_id, page_info in pages.items():
            if "thumbnail" in page_info:
                img_url = page_info["thumbnail"]["source"]
                return f"Found via: '{page_title}'", img_url
                
        return f"Article Found ('{page_title}'), But No Image available", ""
        
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
    
    current_title, current_artist, current_album, current_track = "", "", "", ""
    
    # Generic Tag Pulling
    try:
        is_mp3 = (extension == '.mp3')
        audio = EasyID3(file_path) if is_mp3 else MutagenFile(file_path)
        if audio:
            current_title = audio.get('title', [''])[0] if is_mp3 else audio.get('title', [''])[0] if 'title' in audio else ""
            current_artist = audio.get('artist', [''])[0] if is_mp3 else audio.get('artist', [''])[0] if 'artist' in audio else ""
            current_album = audio.get('album', [''])[0] if is_mp3 else audio.get('album', [''])[0] if 'album' in audio else ""
            current_track = audio.get('tracknumber', [''])[0] if is_mp3 else audio.get('tracknumber', [''])[0] if 'tracknumber' in audio else ""
    except Exception:
        pass

    is_podcast, podcast_reason = analyze_for_podcast(file_path, extension)
    has_art = check_album_art(file_path, extension)

    # --- PROPOSED METADATA LOGIC ---
    raw_title = str(current_title) if str(current_title).strip() else path.stem.replace('_', ' ').replace('-', ' ')
    proposed_title = raw_title.strip().title()
    proposed_artist = str(current_artist).strip().title() if str(current_artist).strip() else "Unknown Artist"
    proposed_album = str(current_album).strip().title() if str(current_album).strip() else "Unknown Album"
    
    proposed_track = ""
    if str(current_track).strip():
        track_match = re.match(r'^(\d+)', str(current_track).strip())
        if track_match:
            proposed_track = f"{int(track_match.group(1)):02d} "

    # --- PROPOSED FILEPATH LOGIC ---
    safe_artist = clean_filename_string(proposed_artist)
    safe_album = clean_filename_string(proposed_album)
    safe_title = clean_filename_string(proposed_title)
    proposed_filename = f"{proposed_track}{safe_title}.mp3"
    proposed_filepath = Path(base_dir) / safe_artist / safe_album / proposed_filename

    # --- DETERMINING THE ACTION ---
    if is_podcast:
        proposed_action = "Skip (Podcast Detected)"
        proposed_filepath = "N/A - Skipped"
        wiki_status, wiki_url = "Skipped (Podcast)", ""
    else:
        proposed_action = "Convert to MP3 & Move" if extension != '.mp3' else "Move/Rename & Update Tags"
        
        # --- WEB SIMULATION TRIGGER ---
        # Only check Wikipedia if the track is music AND lacks art natively
        if has_art == "No":
            print(f"   🔍 Simulating artwork search for: {proposed_artist} - {proposed_album}")
            wiki_status, wiki_url = fetch_wikipedia_album_art(proposed_artist, proposed_album)
        else:
            wiki_status, wiki_url = "Skipped (Art Natively Present)", ""

    return {
        "Current File Path": str(file_path),
        "Current Extension": extension,
        "Is Podcast": "YES" if is_podcast else "No",
        "Has Album Art": has_art,
        "Wikipedia Art Status": wiki_status,
        "Simulated Art URL": wiki_url,
        "Proposed Action": proposed_action,
        "Proposed Title": proposed_title,
        "Proposed Artist": proposed_artist,
        "Proposed Album": proposed_album,
        "Proposed New Filepath": str(proposed_filepath)
    }

def generate_report(directory, output_csv):
    path = Path(directory)
    supported_extensions = {'.mp3', '.wav', '.flac', '.m4a', '.ogg', '.wma'}
    
    headers = [
        "Current File Path", "Current Extension", "Is Podcast", "Has Album Art", 
        "Wikipedia Art Status", "Simulated Art URL", "Proposed Action", 
        "Proposed Title", "Proposed Artist", "Proposed Album", "Proposed New Filepath"
    ]
    
    print(f"Scanning {directory}...")
    count = 0
    
    with open(output_csv, mode='w', newline='', encoding='utf-8') as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=headers)
        writer.writeheader()
        
        for file_path in path.rglob('*'):
            if file_path.is_file() and file_path.suffix.lower() in supported_extensions:
                row_data = get_audio_info(file_path, directory)
                writer.writerow(row_data)
                count += 1
                
    print(f"📊 Report successfully generated with live web lookup simulation! Saved to: {output_csv}")

if __name__ == "__main__":
    if os.path.exists(MUSIC_DIR):
        generate_report(MUSIC_DIR, OUTPUT_CSV)
    else:
        print(f"❌ Error: The directory '{MUSIC_DIR}' does not exist.")

