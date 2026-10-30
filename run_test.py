"""
Quick test script - downloads ONE food video, transcribes it, 
extracts restaurant info, and gives a suggestion.

Run this to see the full pipeline working end-to-end!
"""
import sys
import os
from pathlib import Path

# --- Make ffmpeg available to Whisper (uses bundled binary, no system install needed) ---
import imageio_ffmpeg
_ffmpeg_dir = str(Path(imageio_ffmpeg.get_ffmpeg_exe()).parent)
if _ffmpeg_dir not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
# -----------------------------------------------------------------------------------------

# Add src to path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.step2_downloader import download_video_audio
from src.step3_transcriber import load_whisper_model, transcribe_audio, save_transcript
from src.step4_extractor import setup_gemini, extract_restaurant_info, save_database, load_existing_database
from src.step5_suggester import get_food_suggestion

print("="*60)
print(" FOOD DISCOVERY - FULL PIPELINE TEST")
print("="*60)

# -------------------------------------------------------
# STEP 1: Download a Bengaluru food video from YouTube
# -------------------------------------------------------
TEST_URL = "https://www.youtube.com/watch?v=ToSJ1Xfw_PE"

print("\n[STEP 1] Downloading video audio...")
try:
    audio_path = download_video_audio(TEST_URL)
    print(f"Audio saved: {audio_path}")
except Exception as e:
    print(f"Download failed: {e}")
    sys.exit(1)

# -------------------------------------------------------
# STEP 2: Transcribe the audio
# -------------------------------------------------------
print("\n[STEP 2] Transcribing audio to text...")
print("(Loading Whisper model - first time takes a moment...)")
try:
    model = load_whisper_model("base")
    transcript = transcribe_audio(audio_path, model)

    audio_filename = Path(audio_path).name
    transcript_path = save_transcript(transcript, audio_filename)

    print(f"\nTranscript preview (first 300 chars):")
    print("-" * 40)
    print(transcript[:300] + "..." if len(transcript) > 300 else transcript)
    print("-" * 40)
except Exception as e:
    print(f"Transcription failed: {e}")
    sys.exit(1)

# -------------------------------------------------------
# STEP 3: Extract restaurant info with Gemini
# -------------------------------------------------------
print("\n[STEP 3] Extracting restaurant info with Gemini AI...")
try:
    client = setup_gemini()
    restaurant_info = extract_restaurant_info(transcript, client, Path(transcript_path).name)

    restaurants = load_existing_database()
    restaurants.append(restaurant_info)
    save_database(restaurants)

    print("\nExtracted Info:")
    print("-" * 40)
    import json
    print(json.dumps(restaurant_info, indent=2, ensure_ascii=False))
    print("-" * 40)
except Exception as e:
    print(f"Extraction failed: {e}")
    sys.exit(1)

# -------------------------------------------------------
# STEP 4: Get a suggestion
# -------------------------------------------------------
print("\n[STEP 4] Getting restaurant suggestion...")
suggestion = get_food_suggestion(
    current_location="Bengaluru Railway Station",
    city="Bengaluru",
    arrival_time="2:00 PM",
    available_hours=2.0,
    preferences="vegetarian friendly"
)

print("\n" + "="*60)
print("YOUR RECOMMENDATION:")
print("="*60)
print(suggestion)
