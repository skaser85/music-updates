import csv
import os
import re
from pathlib import Path
from mutagen.easyid3 import EasyID3
from mutagen import File as MutagenFile

import audio_utils

# --- USER DIRECTORY SETTINGS ---
MUSIC_DIR = "/media/steve/New Volume/Music/Music1"
OUTPUT_CSV = "proposed_music_changes.csv"
TRACK_LIMIT = 20000  

# Keep set to False for instant, high-speed calculation testing
ENABLE_WEB_LOOKUP = True 

def gather_track_data(file_path, base_dir):
    path = Path(file_path)
    ext = path.suffix.lower()
    
    try:
        rel_current_path = path.relative_to(Path(base_dir))
    except ValueError:
        rel_current_path = path
        
    title, artist, album, track, albumartist = "", "", "", "", ""
    try:
        is_mp3 = (ext == '.mp3')
        audio = EasyID3(file_path) if is_mp3 else MutagenFile(file_path)
        if audio:
            title = audio_utils.extract_clean_string(audio.get('title', ''))
            artist = audio_utils.extract_clean_string(audio.get('artist', ''))
            album = audio_utils.extract_clean_string(audio.get('album', ''))
            track = audio_utils.extract_clean_string(audio.get('tracknumber', ''))
            albumartist = audio_utils.extract_clean_string(audio.get('albumartist', ''))
    except Exception:
        pass

    is_podcast, podcast_reason = audio_utils.analyze_for_podcast(file_path, ext)
    has_art = audio_utils.check_album_art(file_path, ext)

    # Clean leading characters
    raw_title = title if title.strip() else path.stem.replace('_', ' ').replace('-', ' ')
    p_title = audio_utils.clean_track_title(raw_title).strip().title()
    
    # 🎯 FIX: Apply URL filtering logic to Artist and Album tags
    raw_artist = artist.title() if artist.strip() else "Unknown Artist"
    raw_album = album.title() if album.strip() else "Unknown Album"
    raw_albumartist = albumartist.title() if albumartist.strip() else ""
    
    p_artist = audio_utils.clean_metadata_text(raw_artist, "artist")
    p_album = audio_utils.clean_metadata_text(raw_album, "album")
    p_albumartist = audio_utils.clean_metadata_text(raw_albumartist, "artist") if raw_albumartist else ""

    return {
        "file_path": file_path,
        "rel_current_path": str(rel_current_path),
        "ext": ext,
        "is_podcast": is_podcast,
        "has_art": has_art,
        "p_title": p_title,
        "p_artist": p_artist,
        "p_album": p_album,
        "p_albumartist": p_albumartist
    }

def run_dry_run_scan():
    if not os.path.exists(MUSIC_DIR):
        print(f"❌ Target path context error: '{MUSIC_DIR}' unavailable.")
        return
        
    supported_exts = {'.mp3', '.wav', '.flac', '.m4a', '.ogg', '.wma'}
    
    print(f"🚀 Phase 1: Scanning metadata files into memory mapping blocks...")
    tracks_list = []
    album_artists_map = {} 
    count = 0
    
    for file_path in Path(MUSIC_DIR).rglob('*'):
        if count >= TRACK_LIMIT:
            break
        if file_path.is_file() and file_path.suffix.lower() in supported_exts:
            track_info = gather_track_data(file_path, MUSIC_DIR)
            tracks_list.append(track_info)
            count += 1
            
            if not track_info["is_podcast"] and track_info["p_album"] != "Unknown Album":
                album_key = track_info["p_album"].lower().strip()
                if album_key not in album_artists_map:
                    album_artists_map[album_key] = set()
                album_artists_map[album_key].add(track_info["p_artist"].lower().strip())
                
            if count % 100 == 0:
                print(f"   Gathered {count}/{TRACK_LIMIT} track metadata profiles...")

    headers = [
        "Relative File Path", "Current Extension", "Is Podcast", "Has Album Art", 
        "Wikipedia Art Status", "Simulated Art URL", "Proposed Action", 
        "Proposed Title", "Proposed Artist", "Proposed Album", "Proposed New Path"
    ]
    
    print(f"\n🚀 Phase 2: Evaluating compilation structures and calculating safe target paths...")
    
    with open(OUTPUT_CSV, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        
        for t in tracks_list:
            p_artist = t["p_artist"]
            p_album = t["p_album"]
            p_albumartist = t["p_albumartist"]
            
            album_key = p_album.lower().strip()
            is_compilation = False
            
            if album_key in album_artists_map and len(album_artists_map[album_key]) > 1:
                is_compilation = True

            if p_albumartist:
                folder_artist = p_albumartist
            elif is_compilation:
                folder_artist = "Various Artists" 
            else:
                folder_artist = p_artist

            safe_folder_artist = audio_utils.clean_filename_string(folder_artist)
            safe_album = audio_utils.clean_filename_string(p_album)
            safe_title = audio_utils.clean_filename_string(t["p_title"])
            
            proposed_filename = f"{safe_title}.mp3"
            rel_proposed_path = Path(safe_folder_artist) / safe_album / proposed_filename

            if t["is_podcast"]:
                proposed_action = "Skip (Podcast Detected)"
                rel_proposed_path = "N/A - Skipped"
                wiki_status, wiki_url = "Skipped (Podcast)", ""
            else:
                proposed_action = "Convert to MP3 & Move" if t["ext"] != '.mp3' else "Move/Rename & Update Tags"
                
                if t["has_art"] == "No":
                    if ENABLE_WEB_LOOKUP:
                        wiki_status, wiki_url = audio_utils.fetch_wikipedia_album_art(p_artist, p_album)
                    else:
                        wiki_status, wiki_url = "Simulated (Web Lookup Disabled)", "N/A"
                else:
                    wiki_status, wiki_url = "Skipped (Art Natively Present)", ""

            writer.writerow({
                "Relative File Path": t["rel_current_path"],
                "Current Extension": t["ext"],
                "Is Podcast": "YES" if t["is_podcast"] else "No",
                "Has Album Art": t["has_art"],
                "Wikipedia Art Status": wiki_status,
                "Simulated Art URL": wiki_url,
                "Proposed Action": proposed_action,
                "Proposed Title": t["p_title"],
                "Proposed Artist": p_artist,
                "Proposed Album": p_album,
                "Proposed New Path": str(rel_proposed_path)
            })
            
    print(f"📊 Completed! Output saved smoothly with URL routing patterns scrubbed: {OUTPUT_CSV}")

if __name__ == "__main__":
    run_dry_run_scan()

