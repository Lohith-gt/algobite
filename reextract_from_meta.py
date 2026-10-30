"""Check metadata for the 2 skipped videos and re-extract using description."""
import json, sys, os
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, "src")
from dotenv import load_dotenv
load_dotenv()

from pathlib import Path
from batch_process import extract_with_gemini, load_restaurants, save_restaurants, normalize_city
from google import genai

skipped = {
    "sIi_u2bDbUA": "Coimbatore",
    "-xWGQAdzV9U": "Coimbatore",
}

api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

db = load_restaurants()
existing_urls = {r.get("source_url") for r in db}

for vid_id, city in skipped.items():
    url = f"https://www.youtube.com/watch?v={vid_id}"
    if url in existing_urls:
        print(f"[{vid_id}] Already in DB, skipping.")
        continue

    meta_file = Path(f"videos/transcripts/{vid_id}.meta.json")
    if not meta_file.exists():
        print(f"[{vid_id}] No meta file found.")
        continue

    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    title = meta.get("title", "")
    description = meta.get("description", "")

    print(f"\n=== {vid_id} ===")
    print(f"Title: {title}")
    print(f"Description (first 300): {description[:300]}")

    if not title and not description:
        print("No usable metadata. Skipping.")
        continue

    # Build a synthetic transcript from description + title since Whisper output was corrupted
    transcript = f"Title: {title}\nDescription: {description}"

    print(f"\nExtracting with Gemini using title+description...")
    clean_city = normalize_city(city)
    extracted = extract_with_gemini(
        transcript=transcript,
        city=clean_city,
        video_type="short_form",
        client=client,
        title=title,
        description=description
    )

    if not extracted:
        print(f"[{vid_id}] Gemini could not identify a restaurant even from description.")
        continue

    for r in extracted:
        r["source_url"] = url
        r["source_user_id"] = "test_1"
        r["source_user_name"] = "Test"
        r["city"] = clean_city

    db = load_restaurants()
    existing_urls = {r.get("source_url") for r in db}
    new_to_add = [r for r in extracted if r.get("source_url") not in existing_urls]
    if new_to_add:
        db.extend(new_to_add)
        save_restaurants(db)
        names = ", ".join(r.get("restaurant_name", "?") for r in new_to_add)
        print(f"[{vid_id}] SUCCESS: Saved -> {names}")
    else:
        print(f"[{vid_id}] Already exists in DB.")

print("\nDone!")
db_final = load_restaurants()
user_entries = [r for r in db_final if r.get("source_user_id")]
print(f"Total user-tagged restaurants in DB: {len(user_entries)}")
for r in user_entries:
    print(f"  - {r.get('restaurant_name')} | {r.get('city')}")
