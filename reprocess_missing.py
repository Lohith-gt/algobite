"""
Re-processes the 4 videos that are in known_video_ids but missing from DB.
Run this once to fill in the gaps.
"""
import sys, os, json
from pathlib import Path

# Force UTF-8 stdout
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv
load_dotenv()

from batch_process import process_single_url, load_restaurants, safe_print

# Find which videos are in playlist but missing from DB
DB_PATH = Path("data/restaurants.json")
USERS_PATH = Path("data/users.json")

db = json.loads(DB_PATH.read_text(encoding="utf-8")) if DB_PATH.exists() else []
db_urls = {r.get("source_url", "") for r in db}

users = json.loads(USERS_PATH.read_text(encoding="utf-8")) if USERS_PATH.exists() else {}

print("=" * 60)
print("  RE-PROCESSOR: Finding missing videos per user")
print("=" * 60)

for uid, u in users.items():
    display = u.get("display_name", uid)
    for pl in u.get("linked_playlists", []):
        pl_name = pl.get("name", "Playlist")
        known_ids = pl.get("known_video_ids", [])

        missing = []
        for vid_id in known_ids:
            url = f"https://www.youtube.com/watch?v={vid_id}"
            if url not in db_urls:
                missing.append((vid_id, url))

        if not missing:
            print(f"\n[{display}] Playlist '{pl_name}': All {len(known_ids)} videos already in DB. Nothing to do.")
            continue

        print(f"\n[{display}] Playlist '{pl_name}': {len(missing)} video(s) missing from DB — processing now...")

        for i, (vid_id, url) in enumerate(missing, 1):
            print(f"\n  [{i}/{len(missing)}] Processing {vid_id}")
            print(f"  URL: {url}")
            try:
                extracted, msg = process_single_url(
                    url=url,
                    city="auto",
                    video_type="auto",
                    user_id=uid,
                    user_name=display,
                )
                if extracted:
                    names = ", ".join(r.get("restaurant_name", "?") for r in extracted)
                    print(f"  SUCCESS: Extracted -> {names}")
                else:
                    print(f"  SKIPPED: {msg}")
            except Exception as e:
                safe_print(f"  ERROR: {e}")

print("\n" + "=" * 60)
print("  Re-processing complete!")
# Show final DB state
db_final = json.loads(DB_PATH.read_text(encoding="utf-8")) if DB_PATH.exists() else []
user_entries = [r for r in db_final if r.get("source_user_id") == list(users.keys())[0] if users]
print(f"  Total user-tagged restaurants in DB: {len(user_entries)}")
print("=" * 60)
