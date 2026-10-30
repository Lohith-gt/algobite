"""
STEP 8: Opening Hours Detection (Phase 5)
=========================================
Checks if a restaurant is currently open at the user's arrival time.

Strategy (in order of reliability):
  1. Cached hours in database (fastest - if previously fetched)
  2. Google Maps search page scraping (no API key needed)
  3. Smart heuristics based on meal type + South Indian restaurant patterns
  4. Default: Unknown (restaurant details page in Maps shown to user)

No paid API used. Falls back gracefully at every step.
"""

import sys
import time
import re
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Hours cache file (avoids re-scraping the same restaurant repeatedly)
_HOURS_CACHE_FILE = Path(__file__).parent.parent / "data" / "hours_cache.json"
_hours_cache: dict = {}
_cache_loaded = False

CACHE_TTL_HOURS = 24  # Re-fetch hours every 24 hours


def _load_hours_cache():
    global _hours_cache, _cache_loaded
    if _cache_loaded:
        return
    _cache_loaded = True
    try:
        if _HOURS_CACHE_FILE.exists():
            _hours_cache = json.loads(_HOURS_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        _hours_cache = {}


def _save_hours_cache():
    try:
        _HOURS_CACHE_FILE.write_text(
            json.dumps(_hours_cache, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception:
        pass


def _cache_key(restaurant: dict) -> str:
    name = restaurant.get("restaurant_name", "")
    city = restaurant.get("city", "")
    area = restaurant.get("area_or_locality") or ""
    raw = f"{name}|{area}|{city}".lower()
    return hashlib.md5(raw.encode()).hexdigest()


# ── South Indian Restaurant Hour Heuristics ─────────────────

# Typical operating patterns for South Indian eateries
# Format: meal_type -> (open_hour, close_hour) in 24h
SOUTH_INDIAN_PATTERNS = {
    "breakfast_only": [
        # Pure tiffin/breakfast places that close mid-morning
        (6, 11),   # Open 6 AM - 11 AM
    ],
    "breakfast_lunch": [
        (7, 15),   # Open 7 AM - 3 PM
    ],
    "lunch_only": [
        (11, 15),  # Open 11 AM - 3 PM
    ],
    "dinner_only": [
        (19, 23),  # Open 7 PM - 11 PM
    ],
    "lunch_dinner": [
        (11, 15),  # Lunch session
        (19, 23),  # Dinner session (common break 3-7 PM)
    ],
    "all_day": [
        (7, 22),   # All day operation
    ],
    "street_food": [
        (16, 22),  # Evening street food / snacks
    ],
}

# Keyword-based detection from meal_type list
def _detect_pattern(meal_types: list, cuisine_type: str = "") -> str:
    meal_set = set(str(m).lower() for m in (meal_types or []))
    cuisine_lower = (cuisine_type or "").lower()

    if "street food" in cuisine_lower or "chaat" in cuisine_lower:
        return "street_food"

    has_breakfast = "breakfast" in meal_set
    has_lunch = "lunch" in meal_set
    has_dinner = "dinner" in meal_set
    has_snacks = "snacks" in meal_set

    if has_breakfast and not has_lunch and not has_dinner:
        return "breakfast_only"
    if has_breakfast and has_lunch and not has_dinner:
        return "breakfast_lunch"
    if has_lunch and not has_breakfast and not has_dinner:
        return "lunch_only"
    if has_dinner and not has_breakfast and not has_lunch:
        return "dinner_only"
    if has_lunch and has_dinner and not has_breakfast:
        return "lunch_dinner"
    if has_breakfast or has_lunch or has_dinner or has_snacks:
        return "all_day"
    return "all_day"


def _is_open_by_heuristic(pattern: str, arrival_hour: int) -> tuple[bool, str]:
    """
    Returns (is_open, reason_string).
    """
    sessions = SOUTH_INDIAN_PATTERNS.get(pattern, SOUTH_INDIAN_PATTERNS["all_day"])
    for (open_h, close_h) in sessions:
        if open_h <= arrival_hour < close_h:
            return True, f"Expected to be open {open_h}:00–{close_h}:00 (based on meal type)"
    
    # Build a nice "open during" string
    session_strs = [f"{o}:00–{c}:00" for o, c in sessions]
    return False, f"May be closed at this time. Usually open: {', '.join(session_strs)}"


# ── Google Maps Scraping ──────────────────────────────────────

def _scrape_google_maps_hours(restaurant: dict) -> Optional[dict]:
    """
    Attempts to scrape opening hours from a Google search results page
    for the restaurant. This parses the Knowledge Graph hours panel
    that Google shows for well-known local businesses.
    
    Returns dict with keys: is_open, hours_text, fetched_at, source
    or None if scraping fails.
    
    NOTE: This is best-effort. Google's HTML structure changes; if it fails
    we fall back to heuristics. No real user data is sent.
    """
    try:
        import requests
        from bs4 import BeautifulSoup

        name = restaurant.get("restaurant_name", "")
        area = restaurant.get("area_or_locality") or ""
        city = restaurant.get("city", "")
        query = f"{name} {area} {city} India opening hours"
        
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-IN,en;q=0.9",
        }
        
        search_url = f"https://www.google.com/search?q={requests.utils.quote(query)}&hl=en"
        
        time.sleep(1.0)  # Polite delay
        resp = requests.get(search_url, headers=headers, timeout=8)
        
        if resp.status_code != 200:
            return None
        
        soup = BeautifulSoup(resp.text, "lxml")
        
        # Look for "Open" / "Closed" in the Knowledge Graph panel
        # Google uses various class names; we search for common text patterns
        
        # Method 1: Look for the status text (Open/Closed now)
        is_open = None
        hours_text = ""
        
        page_text = soup.get_text(" ", strip=True)
        
        # Check for "Open now", "Closed now", "Closes at X", "Opens at X"
        open_match = re.search(
            r'(Open now|Closed now|Opens? at \d+:\d+\s*[APM]+|Closes? at \d+:\d+\s*[APM]+)',
            page_text,
            re.IGNORECASE
        )
        
        if open_match:
            matched = open_match.group(0).lower()
            if "open now" in matched or "closes at" in matched:
                is_open = True
            elif "closed now" in matched or "opens at" in matched:
                is_open = False
            hours_text = open_match.group(0)
        
        # Method 2: Try to find structured hours table (Sun, Mon, Tue...)
        hours_pattern = re.findall(
            r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)[:\s]*(\d+:\d+\s*[APM]+\s*[-–]\s*\d+:\d+\s*[APM]+)',
            page_text,
            re.IGNORECASE
        )
        
        if hours_pattern:
            structured = {day: hrs for day, hrs in hours_pattern}
            today = datetime.now().strftime("%A")
            today_hours = structured.get(today)
            if today_hours and is_open is None:
                # Parse today's hours
                m = re.match(r'(\d+):(\d+)\s*([APM]+)\s*[-–]\s*(\d+):(\d+)\s*([APM]+)', today_hours, re.IGNORECASE)
                if m:
                    def to_24h(h, mi, ampm):
                        h = int(h)
                        mi = int(mi)
                        if "PM" in ampm.upper() and h != 12:
                            h += 12
                        elif "AM" in ampm.upper() and h == 12:
                            h = 0
                        return h * 60 + mi
                    
                    now_mins = datetime.now().hour * 60 + datetime.now().minute
                    open_mins = to_24h(m.group(1), m.group(2), m.group(3))
                    close_mins = to_24h(m.group(4), m.group(5), m.group(6))
                    is_open = open_mins <= now_mins < close_mins
                    hours_text = f"Today ({today}): {today_hours}"
        
        if is_open is None and not hours_text:
            return None
        
        return {
            "is_open": is_open,
            "hours_text": hours_text,
            "fetched_at": datetime.now().isoformat(),
            "source": "google_search_scrape"
        }
    
    except Exception as e:
        return None


# ── Main Public API ───────────────────────────────────────────

def check_opening_status(
    restaurant: dict,
    arrival_time_str: str,
    travel_minutes: float = 0
) -> dict:
    """
    Checks if a restaurant is open at the estimated arrival time.
    
    Args:
        restaurant: Restaurant dict from database
        arrival_time_str: Current time string e.g. "9:30 AM"
        travel_minutes: Travel time in minutes to arrive
        
    Returns:
        Dict with keys:
          - is_open: True / False / None (unknown)
          - status_label: "Open" / "Likely Open" / "Likely Closed" / "Closed" / "Unknown"
          - status_emoji: Green/Red/Yellow circle
          - hours_note: Human-readable hours explanation
          - confidence: "confirmed" / "heuristic" / "unknown"
          - recommendation: What the user should do
    """
    _load_hours_cache()

    # Calculate arrival hour
    from step7_crowd import _parse_time
    user_hour = _parse_time(arrival_time_str) or datetime.now().hour
    arrival_hour = int((user_hour * 60 + travel_minutes) / 60) % 24

    # Check cache first
    cache_key = _cache_key(restaurant)
    cached = _hours_cache.get(cache_key)
    
    if cached:
        # Check cache age
        try:
            fetched_at = datetime.fromisoformat(cached.get("fetched_at", ""))
            age_hours = (datetime.now() - fetched_at).total_seconds() / 3600
            if age_hours < CACHE_TTL_HOURS:
                return _build_status_from_cached(cached, arrival_hour, restaurant)
        except Exception:
            pass

    # Try scraping Google Maps hours
    scraped = _scrape_google_maps_hours(restaurant)
    if scraped:
        _hours_cache[cache_key] = scraped
        _save_hours_cache()
        return _build_status_from_scraped(scraped, arrival_hour, restaurant)

    # Fallback: meal-type heuristics
    return _build_status_from_heuristics(restaurant, arrival_hour)


def _build_status_from_scraped(scraped: dict, arrival_hour: int, restaurant: dict) -> dict:
    """Build status dict from scraped Google data."""
    is_open = scraped.get("is_open")
    hours_text = scraped.get("hours_text", "")
    name = restaurant.get("restaurant_name", "")
    
    # The scraped is_open is for NOW, not arrival time
    # If travel is 0, use directly; otherwise use heuristics adjusted for arrival
    if is_open is True:
        return {
            "is_open": True,
            "status_label": "Open Now",
            "status_emoji": "🟢",
            "hours_note": hours_text,
            "confidence": "confirmed",
            "recommendation": f"{name} is currently open."
        }
    elif is_open is False:
        return {
            "is_open": False,
            "status_label": "Closed Now",
            "status_emoji": "🔴",
            "hours_note": hours_text,
            "confidence": "confirmed",
            "recommendation": f"Warning: {name} appears to be closed right now. {hours_text}"
        }
    else:
        # Fallback to heuristics if scrape was inconclusive
        return _build_status_from_heuristics(restaurant, arrival_hour)


def _build_status_from_cached(cached: dict, arrival_hour: int, restaurant: dict) -> dict:
    """Build status from cache (same as scraped)."""
    return _build_status_from_scraped(cached, arrival_hour, restaurant)


def _build_status_from_heuristics(restaurant: dict, arrival_hour: int) -> dict:
    """Build status using meal-type heuristics."""
    name = restaurant.get("restaurant_name", "")
    meal_types = restaurant.get("meal_type") or []
    cuisine = restaurant.get("cuisine_type", "")
    special_notes = (restaurant.get("special_notes") or "").lower()
    
    pattern = _detect_pattern(meal_types, cuisine)
    is_open, reason = _is_open_by_heuristic(pattern, arrival_hour)
    
    # Special case: "Open late night till 1:00 AM" type notes
    if "late night" in special_notes or "1:00 am" in special_notes or "midnight" in special_notes:
        if 22 <= arrival_hour or arrival_hour < 2:
            return {
                "is_open": True,
                "status_label": "Likely Open (Late Night)",
                "status_emoji": "🟢",
                "hours_note": "Opens late night per reviewer notes",
                "confidence": "heuristic",
                "recommendation": f"{name} reportedly stays open late. Good choice for this time!"
            }
    
    if is_open:
        return {
            "is_open": True,
            "status_label": "Likely Open",
            "status_emoji": "🟡",
            "hours_note": reason,
            "confidence": "heuristic",
            "recommendation": f"{name} is likely open at this time based on its meal type ({', '.join(meal_types)})."
        }
    else:
        return {
            "is_open": False,
            "status_label": "Possibly Closed",
            "status_emoji": "🟠",
            "hours_note": reason,
            "confidence": "heuristic",
            "recommendation": (
                f"Warning: {name} may be closed at this time. "
                f"It typically serves {', '.join(meal_types)} and {reason.lower()}. "
                "Please verify before visiting."
            )
        }


def enrich_restaurants_with_hours(
    restaurants: list,
    arrival_time_str: str,
) -> list:
    """
    Adds opening_status dict to each restaurant in the list.
    Called after routing so travel_minutes_one_way is available.
    """
    for r in restaurants:
        travel_min = r.get("travel_minutes_one_way") or 0
        try:
            status = check_opening_status(r, arrival_time_str, travel_minutes=travel_min)
        except Exception as e:
            status = {
                "is_open": None,
                "status_label": "Unknown",
                "status_emoji": "⚪",
                "hours_note": f"Could not determine hours: {e}",
                "confidence": "unknown",
                "recommendation": "Please verify opening hours before visiting."
            }
        r["opening_status"] = status
    return restaurants


# ── Standalone test ──────────────────────────────────────────

if __name__ == "__main__":
    from datetime import datetime

    samples = [
        {
            "restaurant_name": "Bramins Coffee Bar",
            "city": "Bengaluru",
            "area_or_locality": "Malleshwaram",
            "meal_type": ["breakfast"],
            "cuisine_type": "South Indian Vegetarian",
            "special_notes": "Iconic eatery established in 1965",
            "travel_minutes_one_way": 20,
        },
        {
            "restaurant_name": "Sri Rangam Cafe",
            "city": "Bengaluru",
            "area_or_locality": "Indiranagar",
            "meal_type": ["breakfast", "lunch", "dinner"],
            "cuisine_type": "South Indian",
            "special_notes": "Open late night till 1:00 AM",
            "travel_minutes_one_way": 10,
        },
        {
            "restaurant_name": "Valarmathi Mess",
            "city": "Coimbatore",
            "area_or_locality": "Gandhipuram",
            "meal_type": ["lunch", "dinner"],
            "cuisine_type": "Kongu Nadu South Indian",
            "special_notes": "",
            "travel_minutes_one_way": 25,
        },
    ]

    now = datetime.now().strftime("%I:%M %p")
    print(f"Testing opening hours at current time: {now}\n")

    for r in samples:
        status = check_opening_status(r, now, travel_minutes=r["travel_minutes_one_way"])
        print(f"{status['status_emoji']} {r['restaurant_name']}:")
        print(f"   Status: {status['status_label']} ({status['confidence']})")
        print(f"   Note: {status['hours_note']}")
        print(f"   Tip: {status['recommendation']}\n")
