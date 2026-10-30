import json, sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
db = json.loads(Path("data/restaurants.json").read_text(encoding="utf-8"))
user_entries = [r for r in db if r.get("source_user_id")]
print(f"Total in DB: {len(db)} | User-tagged: {len(user_entries)}")
print()
for r in user_entries:
    name = r.get("restaurant_name", "?")
    city = r.get("city", "")
    url = r.get("source_url", "")[-35:]
    print(f"  {name} | {city} | ...{url}")
