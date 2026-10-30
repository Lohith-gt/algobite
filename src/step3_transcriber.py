"""
STEP 3: Audio Transcriber
=========================
This script converts audio from videos into TEXT.

HOW IT WORKS:
- Takes the .mp3 audio files we downloaded in Step 2
- Uses OpenAI's Whisper model to listen to the audio
- Converts everything spoken in the audio to text
- Saves the text to .txt files in the videos/transcripts folder

WHAT IS WHISPER?
- Whisper is a free AI model made by OpenAI
- It can understand speech in 99+ languages including Hindi, Tamil, etc.
- It runs LOCALLY on your computer (no internet needed, no cost!)
- It's extremely accurate even with background noise

WHAT IS A MODEL?
- A "model" here means an AI that's been trained to do a specific task
- Whisper is trained specifically to convert speech to text
- Different model sizes: tiny, base, small, medium, large
  - Smaller = faster but less accurate
  - Larger = slower but more accurate
- We'll use "base" to start (good balance for beginners)
"""

import whisper
import imageio_ffmpeg          # Provides a bundled ffmpeg binary (no system install needed)
import os
from pathlib import Path

# Tell Whisper where to find ffmpeg by adding the bundled binary's folder to PATH
# imageio_ffmpeg.get_ffmpeg_exe() returns the path to the bundled ffmpeg .exe
_ffmpeg_dir = str(Path(imageio_ffmpeg.get_ffmpeg_exe()).parent)
if _ffmpeg_dir not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

# Define folder paths
RAW_VIDEOS_DIR = Path(__file__).parent.parent / "videos" / "raw"
TRANSCRIPTS_DIR = Path(__file__).parent.parent / "videos" / "transcripts"
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)


def load_whisper_model(model_size: str = "base"):
    """
    Loads the Whisper AI model into memory.
    
    Parameters:
        model_size (str): Size of model to use
                          Options: "tiny", "base", "small", "medium", "large"
                          Start with "base" - good balance of speed and accuracy
    
    Returns:
        The loaded Whisper model object
        
    Note: First time you run this, it will DOWNLOAD the model.
          This is a one-time download (around 140MB for "base").
          After that, it loads from your computer.
    """
    print(f"[AI] Loading Whisper '{model_size}' model...")
    print("   (First time: will download the model - please wait)")
    model = whisper.load_model(model_size)
    print(f"[OK] Model loaded successfully!")
    return model


def transcribe_audio(audio_path: str, model) -> str:
    """
    Converts audio speech to text using Whisper.
    
    Parameters:
        audio_path (str): Path to the .mp3 audio file
        model: The loaded Whisper model
        
    Returns:
        str: The full text transcript of what was said in the audio
    """
    audio_path = Path(audio_path)
    
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    
    safe_name = audio_path.name.encode('ascii', errors='replace').decode()
    print(f"\n[AUDIO] Transcribing: {safe_name}")
    print("   This may take a few minutes depending on video length...")
    
    # This is where the magic happens!
    # Whisper listens to the audio and converts it to text
    result = model.transcribe(
        str(audio_path),
        # fp16=False means use 32-bit precision
        # Set True only if you have a GPU (graphics card)
        # Most laptops should use False
        fp16=False,
        
        # verbose=True shows progress as it transcribes
        verbose=True,
        initial_prompt="Indian food vlog review, restaurant, hotel, mess, stall, tiffin, biryani, samosa, dosa, mandi, South India, Hyderabad, Bengaluru, Coimbatore, Karimnagar, Chennai."
    )
    
    # result is a dictionary. result["text"] contains the full transcript
    transcript_text = result["text"].strip()
    
    return transcript_text


def save_transcript(transcript: str, audio_filename: str) -> str:
    """
    Saves the transcript text to a .txt file.
    
    Parameters:
        transcript (str): The text to save
        audio_filename (str): Original audio file name (used to name the transcript)
        
    Returns:
        str: Path where the transcript was saved
    """
    # Create transcript filename: replace .mp3 with .txt
    transcript_filename = Path(audio_filename).stem + ".txt"
    transcript_path = TRANSCRIPTS_DIR / transcript_filename
    
    # Write the text to file
    # encoding="utf-8" ensures Hindi/regional characters are saved correctly
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(transcript)
    
    safe_path = str(transcript_path).encode('ascii', errors='replace').decode()
    print(f"[OK] Transcript saved to: {safe_path}")
    return str(transcript_path)


def transcribe_all_audio_files(model_size: str = "base") -> list:
    """
    Transcribes ALL audio files in the videos/raw folder.
    
    Returns:
        list: Paths to all saved transcript files
    """
    # Find all .mp3 files in the raw videos folder
    # rglob means "search recursively in all subfolders too"
    audio_files = list(RAW_VIDEOS_DIR.glob("*.mp3"))
    
    if not audio_files:
        print("[WARN]  No .mp3 files found in videos/raw/")
        print("   Run step2_downloader.py first to download videos!")
        return []
    
    print(f"[FOLDER] Found {len(audio_files)} audio files to transcribe")
    
    # Load the model ONCE and reuse for all files (more efficient)
    model = load_whisper_model(model_size)
    
    transcript_paths = []
    
    for i, audio_file in enumerate(audio_files, 1):
        print(f"\n{'='*50}")
        print(f"Transcribing {i} of {len(audio_files)}: {audio_file.name}")
        
        # Check if transcript already exists (skip if done)
        transcript_filename = audio_file.stem + ".txt"
        transcript_path = TRANSCRIPTS_DIR / transcript_filename
        
        if transcript_path.exists():
            print(f"[SKIP]  Transcript already exists, skipping: {transcript_filename}")
            transcript_paths.append(str(transcript_path))
            continue
        
        try:
            transcript = transcribe_audio(str(audio_file), model)
            path = save_transcript(transcript, audio_file.name)
            transcript_paths.append(path)
            
            # Show a preview of what was transcribed
            preview = transcript[:200] + "..." if len(transcript) > 200 else transcript
            print(f"\n[NOTE] Preview:\n   {preview}")
            
        except Exception as e:
            print(f"[ERROR] Error transcribing {audio_file.name}: {e}")
    
    print(f"\n[DONE] Transcription complete! {len(transcript_paths)} files processed.")
    return transcript_paths


if __name__ == "__main__":
    # Run transcription on all downloaded audio files
    transcript_paths = transcribe_all_audio_files(model_size="base")
    
    print("\nTranscript files:")
    for p in transcript_paths:
        print(f"  [FILE] {p}")
