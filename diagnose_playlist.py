"""Diagnose which playlist videos are missing from the DB and why."""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

db = json.loads(Path("data/restaurants.json").read_text(encoding="utf-8"))
db_urls = {r.get("source_url", "") for r in db}

known_ids = ['q47p2_MWsr4', 'sIi_u2bDbUA', 'ChX797qPtbU', '-xWGQAdzV9U', 'WAx6c2R89XI', 'y-lR0dLy9_w']
video_titles = {
    'ChX797qPtbU': 'Village Organic Kitchen Chinna Kaparthy',
    'sIi_u2bDbUA': 'Superb Dinner spot in Saibaba Colony',
    'WAx6c2R89XI': 'Coimbatore NEW Non-Veg Dosa Spot',
    'y-lR0dLy9_w': 'Best food spot in Coimbatore',
    'q47p2_MWsr4': 'coimbatore super ana non veg meals (Gowri Mess)',
    '-xWGQAdzV9U': 'Coimbatore famous singapore chicken',
}

print("=== Playlist vs DB Coverage ===")
missing = []
for vid in known_ids:
    url = "https://www.youtube.com/watch?v=" + vid
    in_db = any(vid in u for u in db_urls)
    status = "IN DB" if in_db else "MISSING"
    print(f"  [{status}] {vid} | {video_titles.get(vid, '')}")
    if not in_db:
        missing.append((vid, url))

print()
print(f"Missing from DB: {len(missing)} videos")
for vid, url in missing:
    print(f"  -> {url}")

print()
print("DB user-tagged entries:")
for r in db:
    if r.get("source_user_id"):
        name = r.get("restaurant_name", "Unknown")
        src = r.get("source_url", "")[-45:]
        uid = r.get("source_user_id", "")
        print(f"  {name} | {src} | user={uid}")
