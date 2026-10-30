"""Normalizes city names in restaurants.json (e.g. 'bangalore' -> 'Bengaluru')."""
import json
from pathlib import Path

CITY_NAMES = {
    "bengaluru": "Bengaluru",
    "bangalore": "Bengaluru",
    "banglore":  "Bengaluru",
    "bangaluru": "Bengaluru",
    "coimbatore":"Coimbatore",
    "kovai":     "Coimbatore",
    "chennai":   "Chennai",
    "mumbai":    "Mumbai",
    "delhi":     "Delhi",
    "hyderabad": "Hyderabad",
}

db_path = Path("data/restaurants.json")
data = json.loads(db_path.read_text(encoding="utf-8"))

fixed = 0
for r in data:
    raw = r.get("city", "").strip().lower()
    normalized = CITY_NAMES.get(raw, r.get("city", "Unknown"))
    if normalized != r.get("city"):
        r["city"] = normalized
        fixed += 1

db_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Fixed {fixed} city name(s)")
cities = set(r["city"] for r in data)
print(f"Cities in DB: {cities}")
print(f"Total restaurants: {len(data)}")
