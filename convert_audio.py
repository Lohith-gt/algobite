"""Converts all downloaded webm/m4a files in videos/raw to mp3."""
import imageio_ffmpeg, subprocess
from pathlib import Path

raw = Path("videos/raw")
ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

raw_files = list(raw.glob("*.webm")) + list(raw.glob("*.m4a"))
print(f"Converting {len(raw_files)} files to mp3...")

ok = 0
for f in raw_files:
    mp3 = f.with_suffix(".mp3")
    if mp3.exists():
        ok += 1
        continue
    r = subprocess.run([ffmpeg, "-i", str(f), "-q:a", "4", "-y", str(mp3)], capture_output=True)
    if mp3.exists():
        f.unlink()
        ok += 1
    else:
        print(f"FAILED: {f.name.encode('ascii','replace').decode()}")

print(f"Done: {ok}/{len(raw_files)} converted successfully")
mp3s = list(raw.glob("*.mp3"))
print(f"Total MP3 files in videos/raw: {len(mp3s)}")
