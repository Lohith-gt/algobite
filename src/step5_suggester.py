"""
STEP 5: Restaurant Suggester (The Final Query Engine) + Phase 2 Router
=======================================================================
This is the brain of your project! It answers the question:
"I'm at Bengaluru Railway Station at 2pm. I have 2 hours. Where should I eat?"

HOW IT WORKS (Phase 1 + Phase 2 combined):
- Reads your restaurant database (restaurants.json)
- [PHASE 2] Geocodes the user's location using OpenStreetMap (Nominatim)
- [PHASE 2] Calculates REAL road-based travel time to each restaurant via OSRM
- [PHASE 2] Filters out restaurants that mathematically won't fit in the time window
- Sends only the reachable restaurants to Gemini AI for smart reasoning
- Gemini then picks the best suggestion from the pre-filtered list

WHY PHASE 2 MATTERS:
- Before Phase 2, Gemini *guessed* travel times from training data
- Now, travel times are real road distances — not estimates
- Gemini can focus on quality/preference reasoning, not time math

THIS IS CALLED "RAG" (Retrieval Augmented Generation):
- Retrieval = We retrieve relevant restaurant data + travel data from our sources
- Augmented = We add real distance info to our question
- Generation = Gemini generates a smart answer using that enriched data
- RAG is a very popular and important AI technique!
"""

from google import genai                  # New official Google Gemini SDK
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Fix Windows cp1252 encoding — emojis in Gemini responses crash without this
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Add src/ to path so step6_router can be imported
sys.path.insert(0, str(Path(__file__).parent))
from step6_router import filter_restaurants_by_travel_time
from step7_crowd import enrich_restaurants_with_crowd_and_maps
from step8_hours import enrich_restaurants_with_hours

load_dotenv()

DATA_DIR = Path(__file__).parent.parent / "data"
RESTAURANTS_DB_PATH = DATA_DIR / "restaurants.json"


def setup_gemini():
    """Sets up Gemini AI connection using the new google-genai SDK."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "your_gemini_api_key_here":
        raise ValueError(
            "\n[ERROR] Please set your Gemini API key in the .env file!\n"
            "   Get your free key at: https://aistudio.google.com/apikey"
        )
    client = genai.Client(api_key=api_key)
    return client


def load_restaurant_database() -> list:
    """
    Loads all restaurant data from the JSON file.
    """
    if not RESTAURANTS_DB_PATH.exists():
        print("[WARN]  No restaurant database found!")
        print("   Please run steps 2, 3, and 4 first to build your database.")
        return []
    
    with open(RESTAURANTS_DB_PATH, "r", encoding="utf-8") as f:
        restaurants = json.load(f)
    
    print(f"[FOLDER] Loaded {len(restaurants)} restaurants from database")
    return restaurants


def filter_restaurants_by_city(restaurants: list, city: str) -> list:
    """
    Filters restaurants to only include those in the specified city.
    
    This is a simple pre-filter before we send to Gemini.
    No point asking Gemini to consider Mumbai restaurants when you're in Bengaluru!
    """
    city_lower = city.lower()
    
    filtered = [
        r for r in restaurants
        if (r.get("city") or "").lower().find(city_lower) != -1
        or city_lower.find((r.get("city") or "").lower()) != -1
    ]
    
    if not filtered:
        print(f"[WARN]  No restaurants found for city: {city}")
        print(f"   Cities in database: {set(r.get('city', 'Unknown') for r in restaurants)}")
    else:
        print(f"[OK] Found {len(filtered)} restaurants in {city}")
    
    return filtered


def time_to_meal_type(arrival_time_str: str) -> tuple[str, str]:
    """
    Converts arrival time string to the primary meal type expected at that hour.
    Returns (meal_type, human_description).
    
    e.g. "9:30 AM" -> ("breakfast", "breakfast time")
         "1:00 PM" -> ("lunch", "lunch time")
         "9:00 PM" -> ("dinner", "dinner time")
         "4:30 PM" -> ("snacks", "snack/tea time")
    """
    from step7_crowd import _parse_time, _get_meal_type_for_hour
    hour = _parse_time(arrival_time_str)
    if hour is None:
        hour = datetime.now().hour
    meal = _get_meal_type_for_hour(hour)
    descriptions = {
        "breakfast": "breakfast time (ideal for idli, dosa, pongal, tiffin spots)",
        "lunch":     "lunch time (ideal for rice meals, thali, biriyani spots)",
        "dinner":    "dinner time (ideal for full meals, parotta, non-veg heavy spots)",
        "snacks":    "snack / tea time (ideal for chaat, bajji, chat, light bites)",
    }
    return meal, descriptions.get(meal, meal)


def rank_restaurants_by_meal_time(restaurants: list, meal_type: str) -> list:
    """
    Re-orders restaurants so that meal-type matched ones come first.
    Restaurants that serve the current meal type are ranked higher.
    Others are kept but deprioritised.
    """
    matched   = [r for r in restaurants if meal_type in (r.get("meal_type") or [])]
    unmatched = [r for r in restaurants if meal_type not in (r.get("meal_type") or [])]
    
    if matched:
        print(f"[TIME]  {len(matched)} restaurant(s) match '{meal_type}' time, {len(unmatched)} don't.")
    else:
        print(f"[TIME]  No restaurants specifically match '{meal_type}' — showing all available.")
    
    return matched + unmatched



def get_food_suggestion(
    current_location: str,
    city: str,
    arrival_time: str,
    available_hours: float,
    preferences: str = "",
    use_routing: bool = True,
    dining_minutes: int = 40,
    user_id: Optional[str] = None,
    pre_enriched_restaurants: Optional[list] = None
) -> str:
    """
    The main function! Gets a restaurant suggestion based on your query.

    Parameters:
        current_location (str): Where you are now (e.g., "Bengaluru Railway Station")
        city (str): City you're in (e.g., "Bengaluru")
        arrival_time (str): What time it is (e.g., "2:00 PM")
        available_hours (float): How many hours you have (e.g., 2.0)
        preferences (str): Any extra preferences (e.g., "vegetarian", "light meal")
        use_routing (bool): If True, runs Phase 2 real-distance filtering (default: True)
        dining_minutes (int): Minutes to reserve for eating (default: 40)
        user_id (str): Optional YouTube account ID to only suggest places saved by this user

    Returns:
        str: Gemini's restaurant recommendation with reasoning
    """
    print("\n" + "="*60)
    print("[SEARCH] Finding the best restaurant for you...")
    print(f"   [LOC] Location: {current_location}")
    print(f"   [TIME] Time: {arrival_time}")
    print(f"   [TIMER]  Available: {available_hours} hours")
    if user_id:
        print(f"   [USER] User filter: {user_id}")
    print("="*60)

    # ── TIME-AWARE MEAL TYPE ─────────────────────────────────
    current_meal_type, meal_description = time_to_meal_type(arrival_time)
    print(f"\n[TIME]  It's {arrival_time} — this is {meal_description}")

    if pre_enriched_restaurants:
        city_restaurants = list(pre_enriched_restaurants)
    else:
        # Step 1: Load restaurants
        all_restaurants = load_restaurant_database()
        if not all_restaurants:
            return "[ERROR] No restaurant data available. Please process some videos first!"
    
        # Step 1b: Filter by user if specified
        if user_id:
            all_restaurants = [r for r in all_restaurants if r.get("source_user_id") == user_id]
            if not all_restaurants:
                return (
                    f"[ERROR] No restaurants found in your saved playlist for {city}. "
                    "Sync your Watch Later or food playlist using the extension, or switch to 'All users' in the sidebar."
                )
    
        # Step 2: Filter to the right city
        city_restaurants = filter_restaurants_by_city(all_restaurants, city)
        if not city_restaurants:
            user_msg = f" from your saved playlist" if user_id else ""
            return f"[ERROR] No restaurants found for {city}{user_msg} in your database."
    
        # ── TIME-AWARE MEAL TYPE RANKING ─────────────────────────
        current_meal_type, meal_description = time_to_meal_type(arrival_time)
        print(f"\n[TIME]  It's {arrival_time} — this is {meal_description}")
        city_restaurants = rank_restaurants_by_meal_time(city_restaurants, current_meal_type)
        # ─────────────────────────────────────────────────────────
    
        # ── PHASE 2: Real-time Distance Filtering ────────────────
        if use_routing:
            print(f"\n[PHASE 2] Running real-distance travel filter...")
            city_restaurants = filter_restaurants_by_travel_time(
                restaurants=city_restaurants,
                user_location_str=current_location,
                city=city,
                available_hours=available_hours,
                dining_minutes=dining_minutes
            )
            if not city_restaurants:
                return (
                    f"[ERROR] No restaurants in {city} are reachable within "
                    f"{available_hours} hours from {current_location}. "
                    "Try increasing your available time or adding more restaurants to the database."
                )
            print(f"\n[PHASE 2] {len(city_restaurants)} restaurant(s) passed the travel filter.")
        # ─────────────────────────────────────────────────────────
    
        # ── PHASE 2.1: Crowd Estimation + Google Maps Links ──────
        print(f"\n[PHASE 2.1] Adding crowd predictions and Google Maps links...")
        city_restaurants = enrich_restaurants_with_crowd_and_maps(
            city_restaurants,
            arrival_time_str=arrival_time,
            user_location=current_location,
            user_city=city
        )
        for r in city_restaurants:
            crowd = r.get("crowd_at_arrival", {})
            name = r.get("restaurant_name", "")
            emoji = crowd.get("crowd_emoji", "")
            level = crowd.get("crowd_level", "Unknown")
            arrive = crowd.get("arrival_time", "")
            print(f"   {emoji} {name}: {level} crowd at ~{arrive}")
        # ─────────────────────────────────────────────────────────
    
        # ── PHASE 5: Opening Hours Detection ─────────────────────
        print(f"\n[PHASE 5] Checking opening hours at arrival time...")
        city_restaurants = enrich_restaurants_with_hours(
            city_restaurants,
            arrival_time_str=arrival_time,
        )
        for r in city_restaurants:
            hrs = r.get("opening_status", {})
            name = r.get("restaurant_name", "")
            print(f"   {hrs.get('status_emoji','⚪')} {name}: {hrs.get('status_label','Unknown')} ({hrs.get('confidence','?')})")
        # ─────────────────────────────────────────────────────────
    
    # Sort strictly by: 1) Open status, 2) PROXIMITY (lowest distance_km), 3) total travel time
    city_restaurants.sort(
        key=lambda r: (
            0 if (r.get("opening_status", {}).get("status_label") in ["Open Now", "Likely Open"]) else 1,
            r.get("distance_km") if r.get("distance_km") is not None else 999.0,
            r.get("total_time_minutes") if r.get("total_time_minutes") is not None else 999.0
        )
    )

    for r in city_restaurants:
        crowd = r.get("crowd_at_arrival", {})
        hrs = r.get("opening_status", {})
        name = r.get("restaurant_name", "")
        dist = r.get("distance_km", "?")
        print(f"   [CANDIDATE] {name}: {dist} km away | {hrs.get('status_label','?')} | {crowd.get('crowd_level','?')} crowd")

    # Step 3: Convert restaurant data (now enriched with travel + crowd + hours info) to text for Gemini
    restaurants_text = json.dumps(city_restaurants, indent=2, ensure_ascii=False)


    # Build routing context string for the prompt
    has_distances = any(r.get("distance_km") is not None for r in city_restaurants)
    routing_context = ""
    if use_routing or has_distances:
        routing_context = f"""
CRITICAL — PROXIMITY & SHORTEST TRAVEL DISTANCE (HIGHEST PRIORITY):
The user is physically located at: "{current_location}".
The restaurants below have verified road distances ("distance_km") and one-way drive times ("travel_minutes_one_way") from {current_location}.
- The restaurants are strictly sorted with the physically CLOSEST places first.
- You MUST prioritize restaurants that are CLOSEST to the user's location (lowest distance_km).
- NEVER bypass closer matching restaurants (within 0–3 km) to recommend a distant restaurant (5–10+ km away) across town just because it has a buffet or broad menu, unless the user explicitly requested a buffet in their preferences!
- Option 1 (Primary Recommendation) MUST be the closest suitable, open restaurant to {current_location}.
- Option 2 (Backup Option) should be another nearby alternative.
"""

    # Step 4: Build the query prompt for Gemini
    prompt = f"""
You are a helpful local food guide who knows {city} very well.

The user is at: {current_location}
Current time: {arrival_time} — this is {meal_description}
Available time: {available_hours} hours (they need to return to {current_location} within this time)
Special preferences: {preferences if preferences else "None specified"}
{routing_context}
CRITICAL — OPENING HOURS (Check FIRST before recommending):
Each restaurant has an "opening_status" field with:
  - "status_label": Open Now / Likely Open / Possibly Closed / Closed Now / Unknown
  - "status_emoji": Green/Yellow/Orange/Red circle  
  - "hours_note": What hours it is usually open
  - "confidence": confirmed (scraped from Google) or heuristic (estimated from meal type)
  - "recommendation": What the user should be aware of

If a restaurant's status_label is "Closed Now" or "Possibly Closed", you MUST:
  1. Explicitly warn the user it may be closed at their arrival time
  2. Either suggest them to verify before going, OR skip it and recommend an open alternative

CRITICAL — TIME OF DAY CONTEXT:
It is currently {meal_description}. You MUST strongly prioritise restaurants in the "meal_type" list
that match the current meal period. For example:
  - At 9:30 AM → Prioritise breakfast spots (idli, dosa, pongal, tiffin)
  - At 1:00 PM → Prioritise lunch spots (rice meals, thali, biriyani)
  - At 9:00 PM → Prioritise dinner spots (full meals, parotta, non-veg)
  - At 4:30 PM → Prioritise snack spots (chaat, chat, light bites)

Below is data about restaurants collected from food review videos, pre-filtered to only
include places reachable within the time budget. Each restaurant now includes:
- Real travel time data (distance_km, travel_minutes_one_way)
- A Google Maps link (google_maps_link) for searching the restaurant
- A Google Maps directions link (google_maps_directions) for navigation
- Crowd estimation at arrival time (crowd_at_arrival) with crowd level and tips
- Opening hours status (opening_status) — MOST IMPORTANT field

{restaurants_text}

Based on this information, please suggest the BEST 1-2 restaurants for this person.

Consider (in order of strict priority):
1. **PROXIMITY FIRST ({current_location})**: Strongly prioritize the restaurant with the lowest "distance_km". If a restaurant is 0–2 km away, do NOT recommend a restaurant 5–10 km away!
2. **Opening Hours**: Is this restaurant open at arrival time? Use "opening_status.status_label". NEVER recommend a "Closed Now" restaurant as Option 1.
3. **Meal type match**: Does this restaurant serve {current_meal_type}? Prioritise those that do.
4. **Time Budget**: Must be comfortably within {available_hours} hours total trip.
5. **User preferences**: {preferences if preferences else "None"}
6. **Crowd at arrival**: Use the "crowd_at_arrival" field — prefer lower crowd levels.
7. **Food quality**: Mention reviewer sentiment and must-try dishes.

Format your response EXACTLY like this:
---
## My Recommendation for You

### Option 1: [Restaurant Name]
**Why I'm recommending this:**
[Clear explanation referencing opening status, meal type match, travel time, crowd level, and food quality]

**What to order:** [Must-try dishes from must_try_dishes field]
**Price range:** [Approximate cost from price_range field]
**Travel:** [X km away, ~Y min drive each way]
**Opening Status:** [opening_status emoji + status_label + hours_note]
**Crowd at {arrival_time}:** [crowd_at_arrival emoji + level + description + tip if available]
**Navigate:** [Google Maps link from google_maps_directions field — format as a clickable markdown link]

---
### Option 2 (Backup): [Restaurant Name]
[Same format as above]

---
**Important Notes:**
[Any caveats — opening hours warnings, kitchen closing times, price changes, etc.]
"""
    
    # Setup Gemini and send the prompt
    client = setup_gemini()
    
    WORKING_MODELS = [
        "gemini-3.1-flash-lite",
        "gemini-flash-lite-latest",
        "gemini-3.5-flash",
        "gemini-3.8-flash",
        "gemini-3.6-flash",
        "gemini-3.7-flash"
    ]
    
    print("\n[AI] Gemini is analyzing your options...")
    for model_name in WORKING_MODELS:
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                if response and response.text:
                    # Encode safely — prevent cp1252 charmap crashes from emojis in response
                    safe_text = response.text.encode("utf-8", errors="replace").decode("utf-8")
                    return safe_text
            except Exception as e:
                err = str(e)
                if "429" in err or "503" in err:
                    time.sleep(2)
                    continue
                break
            
    return "[ERROR] Unable to reach Gemini models at this moment. Please try again shortly."


def interactive_query():
    """
    An interactive command-line interface for getting restaurant suggestions.
    """
    print("\n" + "="*60)
    print("   FOOD DISCOVERY ASSISTANT - Phase 1")
    print("="*60)
    print()
    
    city = input("Which city are you visiting? (e.g., Bengaluru): ").strip()
    location = input("Where are you right now? (e.g., Bengaluru Railway Station): ").strip()
    time = input("What time is it now? (e.g., 2:00 PM): ").strip()
    hours = float(input("How many hours do you have total? (e.g., 2): ").strip())
    preferences = input("Any preferences? (vegetarian, budget meal, etc.) [Enter to skip]: ").strip()
    
    suggestion = get_food_suggestion(
        current_location=location,
        city=city,
        arrival_time=time,
        available_hours=hours,
        preferences=preferences
    )
    
    print("\n" + "="*60)
    print("HERE'S YOUR RECOMMENDATION:")
    print("="*60)
    print(suggestion)
    print("="*60)
    
    # Save to file
    output_path = DATA_DIR / "last_suggestion.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"Query: {location} | {time} | {hours} hours\n\n")
        f.write(suggestion)
    print(f"\n[SAVE] Suggestion saved to: {output_path}")


if __name__ == "__main__":
    interactive_query()
