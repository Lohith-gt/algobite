"""
STEP 2: Video Downloader
========================
This script downloads food-related videos from YouTube.

HOW IT WORKS:
- You give it a YouTube URL (a video or a playlist)
- It downloads just the AUDIO (we don't need the full video, just what people say)
- Audio is saved in the videos/raw folder

WHY AUDIO ONLY?
- Audio files are much smaller than video files
- We only need to hear what the food reviewer says
- This saves disk space and processing time

WHAT IS yt-dlp?
- A free, open-source tool for downloading YouTube videos
- Works with 1000+ websites
- We use it as a Python library here
"""

import yt_dlp
import imageio_ffmpeg          # Bundled ffmpeg - no system install needed
import os
from pathlib import Path

# Define where to save downloaded audio files
# Path(__file__) gets the location of this current file
# .parent goes up one folder, then we go into videos/raw
RAW_VIDEOS_DIR = Path(__file__).parent.parent / "videos" / "raw"
RAW_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)  # Create folder if it doesn't exist

# Get the folder containing our bundled ffmpeg binary
# yt-dlp needs to know where ffmpeg is so it can convert audio formats
FFMPEG_DIR = str(Path(imageio_ffmpeg.get_ffmpeg_exe()).parent)


def download_video_audio(url: str) -> str:
    """
    Downloads audio from a YouTube video URL.
    
    Parameters:
        url (str): The YouTube video or playlist URL
        
    Returns:
        str: The file path where the audio was saved
        
    Example:
        path = download_video_audio("https://www.youtube.com/watch?v=xxxxx")
    """
    
    # yt-dlp options - this is how we configure the downloader
    ydl_opts = {
        # 'bestaudio/best' means: get the best quality audio available
        'format': 'bestaudio/best',
        
        # Where to save files and what to name them
        # %(title)s = video title, %(id)s = video ID, %(ext)s = file extension
        'outtmpl': str(RAW_VIDEOS_DIR / '%(title)s_%(id)s.%(ext)s'),
        
        # Convert downloaded audio to mp3 format
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',  # Audio quality (higher = better but larger file)
        }],
        
        # IMPORTANT: Tell yt-dlp exactly where to find ffmpeg
        # Without this, yt-dlp can't convert the downloaded audio to mp3
        'ffmpeg_location': FFMPEG_DIR,
        
        # Don't download if file already exists (saves time on re-runs)
        'nooverwrites': True,
        
        # Suppress verbose output, show only essential info
        'quiet': False,
        'no_warnings': False,
    }
    
    # Use yt-dlp to download
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        # Extract info first to get the filename
        print(f"\n[DOWNLOAD] Downloading audio from: {url}")
        info = ydl.extract_info(url, download=True)
        
        # Build the expected filename
        video_title = info.get('title', 'unknown')
        video_id = info.get('id', 'unknown')
        filename = f"{video_title}_{video_id}.mp3"
        filepath = RAW_VIDEOS_DIR / filename
        
        print(f"[OK] Saved to: {filepath}")
        return str(filepath)


def download_multiple_videos(urls: list) -> list:
    """
    Downloads audio from multiple YouTube videos.
    
    Parameters:
        urls (list): List of YouTube URLs
        
    Returns:
        list: List of file paths where audios were saved
    """
    downloaded_paths = []
    
    for i, url in enumerate(urls, 1):
        print(f"\n{'='*50}")
        print(f"Processing video {i} of {len(urls)}")
        try:
            path = download_video_audio(url)
            downloaded_paths.append(path)
        except Exception as e:
            # If one video fails, we continue with the rest
            print(f"[ERROR] Failed to download {url}: {e}")
            print("   Continuing with next video...")
    
    print(f"\n[DONE] Done! Downloaded {len(downloaded_paths)} of {len(urls)} videos")
    return downloaded_paths


# This block only runs when you execute THIS file directly
# It does NOT run when this file is imported by another file
if __name__ == "__main__":
    # ---- TEST WITH SAMPLE FOOD VIDEOS ----
    # Replace these with your actual YouTube food video URLs about Bengaluru
    
    sample_urls = [
        # Add your YouTube food video URLs here
        # Example format:
        # "https://www.youtube.com/watch?v=VIDEO_ID_HERE",
    ]
    
    if not sample_urls:
        print("[WARN]  No URLs provided!")
        print("   Open this file and add YouTube URLs to the sample_urls list")
        print("   Example: 'https://www.youtube.com/watch?v=xxxxx'")
    else:
        paths = download_multiple_videos(sample_urls)
        print("\nDownloaded files:")
        for p in paths:
            print(f"  📁 {p}")
