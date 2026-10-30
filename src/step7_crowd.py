"""
STEP 7: Google Maps Links + Crowd/Busyness Estimator (Phase 2.1)
=================================================================
Adds two capabilities:
  1. Google Maps navigation links for each restaurant (NO API key needed)
  2. Smart crowd/busyness estimation based on:
     - Time of day (meal rush patterns)
     - Day of week (weekday vs weekend)
     - Review data from our database (crowd_level field)
     - Restaurant type heuristics (street food = early rush, etc.)

APIs Used: NONE — fully local, no API keys required.
"""

from urllib.parse import quote
from datetime import datetime


# ── Google Maps Link Generator ───────────────────────────

def get_google_maps_link(restaurant: dict) -> str:
    """
    Generates a Google Maps search URL for a restaurant.
    
    This creates a link like:
      https://www.google.com/maps/search/?api=1&query=Vidyarthi+Bhavan+Basavanagudi+Bengaluru
    
    When clicked, it opens Google Maps with the restaurant pre-searched,
    showing directions, reviews, Popular Times, and photos.
    
    No API key required — this is just a standard URL.
    """
    name = restaurant.get("restaurant_name", "")
    area = restaurant.get("area_or_locality") or ""
    city = restaurant.get("city", "")
    full_addr = restaurant.get("full_address") or ""
    
    # Build the most specific query possible
    if full_addr:
        query = f"{name}, {full_addr}"
    elif area:
        query = f"{name}, {area}, {city}"
    else:
        query = f"{name}, {city}"
    
    encoded_query = quote(query)
    return f"https://www.google.com/maps/search/?api=1&query={encoded_query}"


def get_google_maps_directions_link(
    restaurant: dict,
    user_location: str = "",
    user_city: str = ""
) -> str:
    """
    Generates a Google Maps DIRECTIONS URL from the user's location
    to the restaurant.
    
    When clicked, opens Google Maps with turn-by-turn navigation ready.
    """
    name = restaurant.get("restaurant_name", "")
    area = restaurant.get("area_or_locality") or ""
    city = restaurant.get("city", "")
    
    destination = f"{name}, {area}, {city}" if area else f"{name}, {city}"
    origin = f"{user_location}, {user_city}" if user_location else ""
    
    dest_encoded = quote(destination)
    
    if origin:
        origin_encoded = quote(origin)
        return f"https://www.google.com/maps/dir/?api=1&origin={origin_encoded}&destination={dest_encoded}&travelmode=driving"
    else:
        return f"https://www.google.com/maps/dir/?api=1&destination={dest_encoded}&travelmode=driving"


# ── Crowd/Busyness Estimation ────────────────────────────

# Typical Indian restaurant rush hour patterns
RUSH_PATTERNS = {
    "breakfast": {
        "peak_hours": [(7, 9)],           # 7 AM - 9 AM
        "moderate_hours": [(9, 10)],       # 9 AM - 10 AM
        "off_peak_after": 10,
    },
    "lunch": {
        "peak_hours": [(12, 14)],          # 12 PM - 2 PM
        "moderate_hours": [(11, 12), (14, 15)],
        "off_peak_after": 15,
    },
    "dinner": {
        "peak_hours": [(19, 21)],          # 7 PM - 9 PM
        "moderate_hours": [(18, 19), (21, 22)],
        "off_peak_after": 22,
    },
    "snacks": {
        "peak_hours": [(16, 18)],          # 4 PM - 6 PM
        "moderate_hours": [(15, 16)],
        "off_peak_after": 18,
    },
}

# Weekend multiplier (weekends are typically 1.3x more crowded)
WEEKEND_MULTIPLIER = 1.3


def _parse_time(time_str: str) -> int | None:
    """
    Parses a time string like '2:00 PM', '14:00', '2pm', 'Now' into
    a 24-hour integer (0-23).
    """
    if not time_str or time_str.lower() == "now":
        return datetime.now().hour
    
    time_str = time_str.strip().upper()
    
    # Try common formats
    for fmt in ["%I:%M %p", "%I:%M%p", "%I %p", "%I%p", "%H:%M", "%H"]:
        try:
            parsed = datetime.strptime(time_str, fmt)
            return parsed.hour
        except ValueError:
            continue
    
    # Last resort: extract digits
    import re
    match = re.search(r"(\d{1,2})", time_str)
    if match:
        h = int(match.group(1))
        if "PM" in time_str and h < 12:
            h += 12
        elif "AM" in time_str and h == 12:
            h = 0
        return h % 24
    
    return datetime.now().hour


def _get_meal_type_for_hour(hour: int) -> str:
    """Maps hour to most likely meal type."""
    if 6 <= hour < 11:
        return "breakfast"
    elif 11 <= hour < 15:
        return "lunch"
    elif 15 <= hour < 18:
        return "snacks"
    else:
        return "dinner"


def estimate_crowd_level(
    restaurant: dict,
    arrival_time_str: str,
    travel_minutes: float = 0,
    is_weekend: bool = None
) -> dict:
    """
    Estimates the crowd/busyness level at a restaurant when the user
    would actually arrive there.
    
    Combines:
      1. Time-of-day rush patterns (breakfast/lunch/dinner peaks)
      2. Weekend vs weekday adjustment
      3. Existing review data from our database
      4. Restaurant type heuristics
    
    Args:
        restaurant: Restaurant dict from database
        arrival_time_str: User's current time (e.g. "2:00 PM")
        travel_minutes: One-way travel time to this restaurant
        is_weekend: True if weekend, None to auto-detect
        
    Returns:
        Dict with crowd estimation details
    """
    # Calculate actual arrival hour
    user_hour = _parse_time(arrival_time_str)
    if user_hour is None:
        user_hour = datetime.now().hour
    
    # Add travel time to get arrival hour at restaurant
    arrival_hour = user_hour + int(travel_minutes / 60)
    arrival_min_remaining = int(travel_minutes % 60)
    arrival_hour_24 = arrival_hour % 24
    
    arrival_time_display = f"{arrival_hour_24}:{arrival_min_remaining:02d}"
    if arrival_hour_24 < 12:
        arrival_ampm = f"{arrival_hour_24 if arrival_hour_24 > 0 else 12}:{arrival_min_remaining:02d} AM"
    elif arrival_hour_24 == 12:
        arrival_ampm = f"12:{arrival_min_remaining:02d} PM"
    else:
        arrival_ampm = f"{arrival_hour_24 - 12}:{arrival_min_remaining:02d} PM"
    
    # Determine if weekend
    if is_weekend is None:
        is_weekend = datetime.now().weekday() >= 5  # Sat=5, Sun=6
    
    # Get the meal type for the arrival hour
    meal_at_arrival = _get_meal_type_for_hour(arrival_hour_24)
    pattern = RUSH_PATTERNS.get(meal_at_arrival, RUSH_PATTERNS["lunch"])
    
    # Determine crowd level from time patterns
    crowd_score = 0  # 0 = empty, 1 = low, 2 = moderate, 3 = high, 4 = packed
    in_peak = False
    in_moderate = False
    
    for start, end in pattern["peak_hours"]:
        if start <= arrival_hour_24 < end:
            crowd_score = 3
            in_peak = True
            break
    
    if not in_peak:
        for start, end in pattern["moderate_hours"]:
            if start <= arrival_hour_24 < end:
                crowd_score = 2
                in_moderate = True
                break
    
    if not in_peak and not in_moderate:
        crowd_score = 1  # Off-peak
    
    # Weekend adjustment (only +1, capped)
    if is_weekend and crowd_score >= 2:
        crowd_score = min(4, crowd_score + 1)
    
    # Factor in existing review data (only nudge by 1)
    review_crowd = restaurant.get("crowd_level") or {}
    review_desc = (review_crowd.get("description") or "").lower()
    
    if in_peak and any(w in review_desc for w in ["packed", "very crowded", "long queue", "long wait"]):
        crowd_score = min(4, crowd_score + 1)
    elif any(w in review_desc for w in ["empty", "quiet", "no crowd"]):
        crowd_score = max(0, crowd_score - 1)
    
    # Map score to labels
    CROWD_LABELS = {
        0: ("Empty", "🟢", "No crowd expected"),
        1: ("Low", "🟢", "Light crowd, easy seating"),
        2: ("Moderate", "🟡", "Some wait possible"),
        3: ("High", "🟠", "Expect a queue or wait"),
        4: ("Very High", "🔴", "Peak rush — long waits likely"),
    }
    
    label, emoji, description = CROWD_LABELS[crowd_score]
    
    # Build recommendation
    best_time = review_crowd.get("best_time_to_visit") or ""
    usually_crowded = review_crowd.get("usually_crowded_at") or ""
    
    tip = ""
    if crowd_score >= 3 and best_time:
        tip = f"Tip: Reviewer says best time is {best_time}"
    elif crowd_score >= 3:
        tip = f"Tip: Try arriving 30 min before or after the {meal_at_arrival} rush"
    elif crowd_score <= 1:
        tip = "Good timing — you should get a seat easily"
    
    return {
        "arrival_time": arrival_ampm,
        "crowd_level": label,
        "crowd_emoji": emoji,
        "crowd_score": crowd_score,
        "crowd_description": description,
        "meal_type_at_arrival": meal_at_arrival,
        "is_weekend": is_weekend,
        "tip": tip,
        "review_best_time": best_time,
        "review_usually_crowded": usually_crowded,
    }


def enrich_restaurants_with_crowd_and_maps(
    restaurants: list,
    arrival_time_str: str,
    user_location: str = "",
    user_city: str = ""
) -> list:
    """
    Enriches a list of restaurants with:
      - Google Maps link (search + directions)
      - Crowd estimation at arrival time
    
    This should be called AFTER step6_router's travel time filtering,
    so that travel_minutes_one_way is already available.
    """
    for r in restaurants:
        # Add Google Maps links
        r["google_maps_link"] = get_google_maps_link(r)
        r["google_maps_directions"] = get_google_maps_directions_link(
            r, user_location, user_city
        )
        
        # Estimate crowd at arrival
        travel_min = r.get("travel_minutes_one_way") or 0
        crowd = estimate_crowd_level(r, arrival_time_str, travel_minutes=travel_min)
        r["crowd_at_arrival"] = crowd
    
    return restaurants


# ── Standalone test ──────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    
    # Test with a sample restaurant
    sample = {
        "restaurant_name": "Vidyarthi Bhavan",
        "city": "Bengaluru",
        "area_or_locality": "Basavanagudi",
        "cuisine_type": "South Indian Vegetarian",
        "meal_type": ["breakfast", "lunch"],
        "crowd_level": {
            "description": "Usually packed during breakfast rush",
            "best_time_to_visit": "Before 7:30 AM or after 10 AM",
            "usually_crowded_at": "8:00 AM - 10:00 AM"
        },
        "travel_minutes_one_way": 15,
    }
    
    print("=" * 60)
    print("  PHASE 2.1: GOOGLE MAPS + CROWD ESTIMATION TEST")
    print("=" * 60)
    
    # Test Maps links
    maps_link = get_google_maps_link(sample)
    directions_link = get_google_maps_directions_link(sample, "Majestic", "Bengaluru")
    print(f"\nMaps Search: {maps_link}")
    print(f"Directions:  {directions_link}")
    
    # Test crowd estimation at different times
    for test_time in ["7:30 AM", "9:00 AM", "11:00 AM", "1:00 PM", "6:00 PM"]:
        crowd = estimate_crowd_level(sample, test_time, travel_minutes=15)
        print(f"\n  At {test_time} (arrive ~{crowd['arrival_time']}):")
        print(f"    {crowd['crowd_emoji']} {crowd['crowd_level']} — {crowd['crowd_description']}")
        print(f"    Meal type: {crowd['meal_type_at_arrival']}")
        if crowd['tip']:
            print(f"    {crowd['tip']}")
