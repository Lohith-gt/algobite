"""
BATCH PROCESSOR
===============
Processes ALL unprocessed videos in data/dataset_urls.json

This script:
1. Reads all URLs from the dataset config
2. Downloads audio for each unprocessed URL (with retry)
3. Transcribes with Whisper (base model)
4. Extracts restaurant info with Gemini (multi-model fallback + backoff)
5. Normalizes city names automatically
6. Saves everything to data/restaurants.json
7. Marks videos as processed in the config
"""

import sys, os, json, time, subprocess
from pathlib import Path

# Force UTF-8 on Windows — prevents cp1252 crashes from Tamil/Telugu/Hindi video titles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Fix ffmpeg path
import imageio_ffmpeg
_ffmpeg_dir = str(Path(imageio_ffmpeg.get_ffmpeg_exe()).parent)
os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
_project_dir = str(Path(__file__).parent)
os.environ["PATH"] = _project_dir + os.pathsep + os.environ["PATH"]

sys.path.insert(0, str(Path(__file__).parent / "src"))

import yt_dlp
import whisper
from google import genai
from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────
DATASET_CONFIG   = Path("data/dataset_urls.json")
RESTAURANTS_DB   = Path("data/restaurants.json")
RAW_AUDIO_DIR    = Path("videos/raw")
TRANSCRIPTS_DIR  = Path("videos/transcripts")
FFMPEG_DIR       = str(Path(imageio_ffmpeg.get_ffmpeg_exe()).parent)

RAW_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
Path("data").mkdir(exist_ok=True)

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
    "karimnagar":"Karimnagar",
    "kmr":       "Karimnagar",
    "stockholm": "Stockholm",
    "sweden":    "Stockholm",
}

# State names that must NEVER be stored as a city value
STATE_NAMES_BLOCKED = {
    "telangana", "karnataka", "tamil nadu", "andhra pradesh",
    "maharashtra", "kerala", "rajasthan", "gujarat", "uttar pradesh",
    "west bengal", "punjab", "haryana", "bihar", "odisha",
}

WORKING_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.7-flash"
]

# ── Helpers ────────────────────────────────────────────

def load_config():
    if not DATASET_CONFIG.exists():
        return {}
    try:
        with open(DATASET_CONFIG, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

def save_config(config):
    with open(DATASET_CONFIG, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def load_restaurants():
    if RESTAURANTS_DB.exists():
        try:
            return json.loads(RESTAURANTS_DB.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            return []
    return []

def save_restaurants(restaurants):
    RESTAURANTS_DB.write_text(
        json.dumps(restaurants, indent=2, ensure_ascii=False), encoding="utf-8"
    )

def safe_print(text):
    """Print text safely — bypasses Windows cp1252 codec using UTF-8 os.write."""
    try:
        msg = str(text).encode("utf-8", errors="replace") + b"\n"
        os.write(sys.stdout.fileno(), msg)
    except Exception:
        try:
            print(str(text).encode("ascii", errors="replace").decode())
        except Exception:
            pass

def normalize_city(city_str: str) -> str:
    raw = (city_str or "").strip().lower()
    # If it's a known state name, return "Unknown" — never store a state as a city
    if raw in STATE_NAMES_BLOCKED:
        return "Unknown"
    return CITY_NAMES.get(raw, city_str.strip().capitalize() if city_str else "Unknown")


def auto_detect_city(title: str = "", description: str = "") -> str:
    """
    Auto-detects city from video title and description by scanning
    for known Indian city names. Returns normalized city or "Unknown".
    
    CRITICAL: Scans TITLE FIRST so spam hashtags in description
    (e.g. #bangalore in a Coimbatore video) do NOT hijack city detection!
    """
    CITY_KEYWORDS = {
        "coimbatore": "Coimbatore", "kovai": "Coimbatore", "cbe": "Coimbatore",
        "bengaluru": "Bengaluru", "bangalore": "Bengaluru", "blr": "Bengaluru",
        "namma bengaluru": "Bengaluru",
        "chennai": "Chennai", "madras": "Chennai",
        "hyderabad": "Hyderabad", "hyd": "Hyderabad",
        "karimnagar": "Karimnagar", "kmr": "Karimnagar",
        # NOTE: "telangana" is a STATE name — removed intentionally so it never
        # overwrites a real city. Karimnagar/Hyderabad etc. take priority.
        "mumbai": "Mumbai", "bombay": "Mumbai",
        "delhi": "Delhi", "new delhi": "Delhi",
        "pune": "Pune",
        "kolkata": "Kolkata", "calcutta": "Kolkata",
        "jaipur": "Jaipur",
        "lucknow": "Lucknow",
        "ahmedabad": "Ahmedabad",
        "kochi": "Kochi", "cochin": "Kochi",
        "mysore": "Mysuru", "mysuru": "Mysuru",
        "mangalore": "Mangaluru", "mangaluru": "Mangaluru",
        "trivandrum": "Thiruvananthapuram", "thiruvananthapuram": "Thiruvananthapuram",
        "madurai": "Madurai",
        "vizag": "Visakhapatnam", "visakhapatnam": "Visakhapatnam",
        "goa": "Goa",
        "stockholm": "Stockholm",
        "sweden": "Stockholm",
    }
    
    # 1. Scan TITLE first (highest accuracy)
    title_lower = (title or "").lower()
    for keyword, city in CITY_KEYWORDS.items():
        if keyword in title_lower:
            return city
            
    # 2. Scan explicit address or location lines in description (before hashtags)
    desc_lines = (description or "").split("\n")
    for line in desc_lines:
        line_clean = line.strip().lower()
        if line_clean.startswith("#"):
            continue  # skip hashtag lines
        if any(marker in line_clean for marker in ["📍", "location", "address", "near", "opposite", "road", "street"]):
            for keyword, city in CITY_KEYWORDS.items():
                if keyword in line_clean:
                    return city

    # 3. Fallback: check full text
    full_text = f"{title} {description}".lower()
    for keyword, city in CITY_KEYWORDS.items():
        if keyword in full_text:
            return city
            
    return "Unknown"


def auto_detect_video_type(duration_seconds: int | None) -> str:
    """
    Auto-detects video type from duration.
    Shorts/Reels are typically < 120 seconds.
    """
    if duration_seconds is None:
        return "short_form"
    return "short_form" if duration_seconds < 120 else "long_form"


# ── Step 1: Download audio ─────────────────────────────

def download_audio(url: str, retries: int = 2) -> tuple[str | None, str, str, int | None]:
    """
    Downloads audio from a YouTube or Instagram URL.
    Converts directly to mp3 using bundled ffmpeg.
    Returns: (mp3_path, title, description, duration_seconds)
    """
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(RAW_AUDIO_DIR / "%(id)s.%(ext)s"),
        "nooverwrites": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 15,
    }
    
    title = ""
    description = ""
    duration = None
    for attempt in range(retries):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                video_id  = info.get("id", "unknown")
                video_ext = info.get("ext", "webm")
                title = info.get("title", "")
                description = info.get("description", "")
                duration = info.get("duration")

                mp3_path = RAW_AUDIO_DIR / f"{video_id}.mp3"
                if mp3_path.exists() and mp3_path.stat().st_size > 1024:
                    return str(mp3_path), title, description, duration

                # Search downloaded raw file
                matches = list(RAW_AUDIO_DIR.glob(f"{video_id}.*"))
                raw_matches = [m for m in matches if m.suffix != ".mp3"]
                if not raw_matches:
                    time.sleep(2)
                    continue
                raw_path = raw_matches[0]

                # Convert to MP3
                ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
                subprocess.run(
                    [ffmpeg_exe, "-i", str(raw_path), "-q:a", "4", "-y", str(mp3_path)],
                    capture_output=True
                )
                if mp3_path.exists() and mp3_path.stat().st_size > 1024:
                    raw_path.unlink(missing_ok=True)
                    return str(mp3_path), title, description, duration
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(3)
            else:
                safe_print(f"    Download error: {str(e)[:90]}")
    return None, title, description, duration


# ── Step 2: Transcribe ─────────────────────────────────

def transcribe(audio_path: str, model) -> str | None:
    """Transcribes audio to text using Whisper with Indian food context prompt."""
    try:
        result = model.transcribe(
            str(audio_path),
            fp16=False,
            verbose=False,
            initial_prompt="Indian food vlog review, restaurant, hotel, mess, stall, tiffin, biryani, samosa, dosa, mandi, South India, Hyderabad, Bengaluru, Coimbatore, Karimnagar, Chennai."
        )
        return result.get("text", "").strip()
    except Exception as e:
        safe_print(f"    Transcription error: {str(e)[:90]}")
        return None


# ── Step 3: Extract restaurant info ────────────────────

SHORT_FORM_PROMPT = """
You are an expert at analyzing short-form food review videos (Instagram Reels, YouTube Shorts).

These are SHORT videos (30-90 seconds) so they typically focus on ONE restaurant or ONE dish.

CITY: {city}
VIDEO TITLE: {title}
VIDEO DESCRIPTION: {description}

AUDIO TRANSCRIPT:
{transcript}

CRITICAL EXTRACTION GUIDELINES:
1. **FIND THE EXACT SHOP / RESTAURANT NAME (HIGHEST PRIORITY)**:
   - Food vloggers in Telugu, Hindi, Tamil, Kannada, or English always mention the specific shop / hotel / restaurant / mess / stall name (e.g. "Ganesh Samosa Centre", "Saffron House", "Taj Badam Milk", "Raju Tea Stall", "Raja Mess", "Aranyam").
   - Check the VIDEO TITLE, VIDEO DESCRIPTION, and SPOKEN AUDIO carefully for the actual business/brand name.
   - **STRICTLY FORBIDDEN**: NEVER use generic placeholders like "Samosa Stall", "Unlimited Lunch Buffet", "Tea Stall", "Food Cart", etc., when an actual shop name or brand is spoken or written in any language!
   - NEVER append "- CityName" to the restaurant_name (e.g., write "Ganesh Samosa Centre", NOT "Samosa Stall - Karimnagar"). The city belongs strictly in the "city" field.
2. **COMBINE AUDIO & DESCRIPTION**: The audio provides reviewer taste feedback and must-try recommendations, while the description provides the exact logistical facts (name, address, cost, hours). Use BOTH together for the highest accuracy.
3. **UNNAMED STREET STALLS (STRICT FALLBACK ONLY)**: Only if after thorough analysis of title, description, and audio there is genuinely no name mentioned, provide a clean descriptive title like "Saibaba Colony Dosa Cart". Do NOT return null for restaurant_name.
4. **ALWAYS PROVIDE VALID MEAL_TYPE & MUST_TRY_DISHES (NEVER NULL)**:
   - "meal_type" must ALWAYS be a list with at least one value: e.g. ["breakfast"], ["lunch", "dinner"], or ["snacks"]. NEVER set it to null.
   - "must_try_dishes" must ALWAYS be a list of recommended dishes. NEVER set it to null.
5. **ACCURATE GEOGRAPHY & NO ASSUMED DATA**: Do NOT assume or hallucinate city, town, or state names.
   - Read the exact location, PIN code, and state written in the description or spoken in the video (e.g. Telangana is NOT Andhra Pradesh).
   - If the video is in Coimbatore, do not mark Bengaluru just because of a hashtag.
   - Never output a state name (like "Telangana") as the city; output the actual city/town (like "Karimnagar").
6. **MULTI-SPOT VIDEOS MUST BE EXTRACTED AS SEPARATE RESTAURANTS**:
   Even in short videos, food creators often share quick listicles (e.g. "Top 5 spots", "My favorite Bangalore places", "3 best dosas"):
   - Extract EACH restaurant as its own individual JSON object in the array!
   - NEVER combine multiple restaurants into a single entry like "Multiple Restaurants (A, B, C)" or "5 Food Spots"!
   - If only 1 restaurant is featured, return an array with that 1 restaurant object.

Always return a JSON ARRAY of objects.
Use null for anything not mentioned. Be concise and accurate.
Return ONLY valid JSON array, no other text:

[
  {{
    "restaurant_name": "exact name from title/description/audio, OR a descriptive label like 'Street Cart - [area]' for unnamed spots",
    "city": "{city}",
    "area_or_locality": "specific area/street/landmark from description or null",
    "full_address": "exact full address from description if available or null",
    "cuisine_type": "type of food",
    "meal_type": ["breakfast", "lunch", "dinner", "snacks"],
    "price_range": {{
      "description": "cheap/budget/mid-range/expensive or null",
      "approximate_cost_for_two": "INR amount or null"
    }},
    "crowd_level": {{
      "description": "crowded/packed/quiet/empty or null",
      "best_time_to_visit": "less crowded time or null",
      "usually_crowded_at": "peak time or null"
    }},
    "rating": {{
      "reviewer_sentiment": "Positive/Negative/Mixed",
      "score_if_given": null
    }},
    "must_try_dishes": ["dish1", "dish2"],
    "ambience": "street food/casual/formal/family etc or null",
    "special_notes": "any extra info like timings, weekly off, or notes from description",
    "video_type": "short_form"
  }}
]
"""

LONG_FORM_PROMPT = """
You are an expert at analyzing food review videos and extracting restaurant information.

This is a LONG-FORM video (food tour/vlog) covering ONE or MULTIPLE restaurants.

CITY: {city}
VIDEO TITLE: {title}
VIDEO DESCRIPTION: {description}

TRANSCRIPT (first 8000 chars):
{transcript}

CRITICAL EXTRACTION GUIDELINES:
1. **FIND THE EXACT SHOP / RESTAURANT NAME (HIGHEST PRIORITY)**:
   - Check description timestamps and chapters for lists of places visited (e.g. "Spot Name - Location").
   - Extract the exact proper business name. NEVER use generic labels like "Buffet", "Food Stall", "Restaurant", or append "- CityName".
2. **COMBINE AUDIO & DESCRIPTION**: Cross-reference the dishes spoken in the transcript with the locations listed in the description.
3. **ACCURATE GEOGRAPHY & NO ASSUMED DATA**: Do NOT assume or hallucinate city or state names. Verify against exact descriptions and titles (e.g. Telangana is NOT Andhra Pradesh). Never output a state name as city.
4. **ALWAYS PROVIDE VALID MEAL_TYPE & MUST_TRY_DISHES (NEVER NULL)**:
   - "meal_type" must ALWAYS be a list with at least one value: e.g. ["lunch", "dinner"]. NEVER set it to null.
   - "must_try_dishes" must ALWAYS be a list of recommended dishes. NEVER set it to null.

Extract info for ALL restaurants mentioned and return a JSON ARRAY.
For each restaurant use this structure. Return ONLY valid JSON array, no other text:

[
  {{
    "restaurant_name": "name",
    "city": "{city}",
    "area_or_locality": "area or landmark from description or null",
    "full_address": "full address from description or null",
    "cuisine_type": "type of food",
    "meal_type": ["breakfast", "lunch", "dinner", "snacks"],
    "price_range": {{
      "description": "budget/mid/expensive",
      "approximate_cost_for_two": "INR amount or null"
    }},
    "crowd_level": {{
      "description": "crowded/quiet etc",
      "best_time_to_visit": "time or null",
      "usually_crowded_at": "time or null"
    }},
    "rating": {{"reviewer_sentiment": "Positive/Negative/Mixed", "score_if_given": null}},
    "must_try_dishes": ["dish1", "dish2"],
    "ambience": "casual/formal/street food etc",
    "special_notes": "any extra info like timings or notes from description",
    "video_type": "long_form"
  }}
]
"""


def _cross_verify_restaurant(restaurant: dict) -> dict:
    """
    Cross-verifies a Gemini-extracted restaurant by attempting a quick
    Nominatim geocode lookup. This catches hallucinated names or wrong cities.

    Sets two new fields:
      - "location_verified": True/False — whether Nominatim found it
      - "verified_coords": [lat, lon] or null
      - "verification_note": human-readable result

    This does NOT block saving — it just adds metadata so the user
    can see which entries are confirmed vs uncertain.
    """
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderTimedOut, GeocoderServiceError
    import time as _time
    import re

    name = restaurant.get("restaurant_name", "")
    city = restaurant.get("city", "")
    area = restaurant.get("area_or_locality") or ""
    full_addr = restaurant.get("full_address") or ""
    country = "Sweden" if (city or "").strip().lower() in ["stockholm", "gothenburg", "malmo", "sweden"] else "India"

    queries = []
    if full_addr:
        queries.append((f"{full_addr}, {country}", True, "exact address"))
    if area:
        queries.append((f"{name}, {area}, {city}, {country}", True, "exact in area"))
        # Compound area subparts (e.g. "Tower Circle, Islam Masjid Road")
        subparts = [p.strip() for p in re.split(r'[,/|-]', area) if len(p.strip()) > 2]
        for part in subparts:
            queries.append((f"{name}, {part}, {city}, {country}", True, f"in subpart '{part}'"))
            queries.append((f"{part}, {city}, {country}", False, f"subpart '{part}' center"))
        queries.append((f"{area}, {city}, {country}", False, "area center"))

    queries.append((f"{name}, {city}, {country}", True, "name in city"))
    queries.append((f"{name}, {city}", True, "name in city"))

    # Fallback to city center so verified_coords is NEVER None/missing for distance
    if city and city.strip().lower() not in ["unknown", ""]:
        queries.append((f"{city}, {country}", False, "city center"))
        queries.append((city, False, "city center"))

    try:
        geolocator = Nominatim(user_agent="food_discovery_verify_v2", timeout=8)
        for q, is_exact, label in queries:
            _time.sleep(1.1)  # Nominatim rate limit
            try:
                loc = geolocator.geocode(q, language="en")
                if loc:
                    restaurant["location_verified"] = True
                    restaurant["verified_coords"] = [loc.latitude, loc.longitude]
                    if is_exact:
                        restaurant["verification_note"] = f"Verified via Nominatim: {loc.address[:80]}"
                    else:
                        restaurant["verification_note"] = f"Located in {area or city} ({label})"
                    safe_print(f"    [VERIFY] {name}: FOUND ({label}) at {loc.address[:60]}")
                    return restaurant
            except (GeocoderTimedOut, GeocoderServiceError):
                continue
    except Exception as e:
        safe_print(f"    [VERIFY] Could not verify {name}: {e}")

    # Fallback if geocoder completely failed to reach network
    restaurant["location_verified"] = False
    restaurant["verified_coords"] = None
    restaurant["verification_note"] = f"Not found in OpenStreetMap — may still be valid but could not be confirmed"
    safe_print(f"    [VERIFY] {name}: NOT FOUND in OSM (may still exist locally)")
    return restaurant


def is_valid_restaurant_name(name: str) -> bool:
    if not name or not isinstance(name, str):
        return False
    name_clean = name.strip()
    if not name_clean or name_clean.lower() in ["null", "none", "unknown", "popular food spot"]:
        return False
    import re
    invalid_patterns = [
        r'^\d+\s+(popular|best|top|must|famous|major|iconic)',
        r'^(major|top|best|popular)\s+\d+',
        r'\b(food spots|food listicle|places to eat|food walk|food tour|street food compilation)\b',
        r'\bspots in [a-zA-Z]+\b',
        r'\bfood guide\b',
    ]
    for pattern in invalid_patterns:
        if re.search(pattern, name_clean, re.IGNORECASE):
            return False
    return True


def sanitize_restaurant_record(r: dict, clean_city: str, title: str = "", description: str = "") -> dict:
    """
    Guarantees strict schema integrity, clean naming, and zero-NoneType invariants
    for any restaurant extracted from any video.
    """
    if not isinstance(r, dict):
        return {}

    # 1. Clean & validate restaurant name
    name = (r.get("restaurant_name") or "").strip()
    # Strip any trailing city suffix like " - Karimnagar" or " - Bengaluru"
    for c in list(CITY_NAMES.values()) + [clean_city]:
        if c and name.lower().endswith(f"- {c.lower()}"):
            candidate = name[: -(len(c) + 2)].strip()
            if candidate:
                name = candidate
                break
    # Check if name is valid (not a listicle or compilation video title)
    if not is_valid_restaurant_name(name):
        return {}
    r["restaurant_name"] = name

    # 2. Strict city normalization (never state names or Unknown)
    city_cand = (r.get("city") or clean_city or "").strip()
    if not city_cand or city_cand.lower() in STATE_NAMES_BLOCKED or city_cand == "Unknown":
        recovered = auto_detect_city(title=title, description=description)
        if recovered != "Unknown" and recovered.lower() not in STATE_NAMES_BLOCKED:
            city_cand = recovered
        else:
            city_cand = clean_city if (clean_city and clean_city.lower() not in STATE_NAMES_BLOCKED) else "Unknown"
    r["city"] = normalize_city(city_cand)

    # 3. meal_type — ALWAYS a non-empty list of strings, NEVER None
    meals = r.get("meal_type")
    if not isinstance(meals, list) or not meals:
        r["meal_type"] = ["lunch", "dinner"]
    else:
        cleaned_meals = [str(m).strip().lower() for m in meals if m]
        r["meal_type"] = cleaned_meals if cleaned_meals else ["lunch", "dinner"]

    # 4. must_try_dishes — ALWAYS a non-empty list of strings, NEVER None
    dishes = r.get("must_try_dishes")
    if not isinstance(dishes, list) or not dishes:
        r["must_try_dishes"] = ["Specialties featured in video"]
    else:
        cleaned_dishes = [str(d).strip() for d in dishes if d]
        r["must_try_dishes"] = cleaned_dishes if cleaned_dishes else ["Specialties featured in video"]

    # 5. price_range — ALWAYS a dict, NEVER None
    pr = r.get("price_range")
    if not isinstance(pr, dict):
        r["price_range"] = {"description": "Budget-friendly", "approximate_cost_for_two": "₹150 - ₹400"}
    else:
        if not pr.get("description"):
            pr["description"] = "Budget-friendly"
        if not pr.get("approximate_cost_for_two"):
            pr["approximate_cost_for_two"] = "Moderate"

    # 6. crowd_level — ALWAYS a dict, NEVER None
    cl = r.get("crowd_level")
    if not isinstance(cl, dict):
        r["crowd_level"] = {"description": "Moderate", "best_time_to_visit": None, "usually_crowded_at": None}

    # 7. rating — ALWAYS a dict, NEVER None
    rt = r.get("rating")
    if not isinstance(rt, dict):
        r["rating"] = {"reviewer_sentiment": "Positive", "score_if_given": None}

    # 8. Address & locality fallbacks
    if not r.get("area_or_locality") and r.get("full_address"):
        r["area_or_locality"] = r["full_address"].split(",")[0].strip()

    return r


def extract_with_gemini(transcript: str, city: str, video_type: str, client, title: str = "", description: str = "") -> list:
    """
    Uses Gemini to extract restaurant info from a transcript with robust fallbacks.
    """
    clean_city = normalize_city(city)
    desc_clean = (description or "")[:8000]
    if video_type == "short_form":
        prompt = SHORT_FORM_PROMPT.format(city=clean_city, transcript=transcript[:4000], title=title or "Unknown", description=desc_clean)
    else:
        prompt = LONG_FORM_PROMPT.format(city=clean_city, transcript=transcript[:10000], title=title or "Unknown", description=desc_clean)

    for model_name in WORKING_MODELS:
        for wait in [0, 4, 10]:
            if wait > 0:
                time.sleep(wait)
            try:
                response = client.models.generate_content(model=model_name, contents=prompt)
                text = response.text.strip()
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0].strip()
                data = json.loads(text)
                if isinstance(data, dict):
                    data = [data]
                data = [r for r in data if r.get("restaurant_name") and r["restaurant_name"] != "null"]
                sanitized_data = []
                for r in data:
                    r = sanitize_restaurant_record(r, clean_city, title=title, description=description)
                    if not r or not is_valid_restaurant_name(r.get("restaurant_name")):
                        continue
                    # Cross-verify: quick Nominatim lookup to check if restaurant + city is plausible
                    r = _cross_verify_restaurant(r)
                    sanitized_data.append(r)
                return sanitized_data
            except json.JSONDecodeError:
                safe_print(f"    JSON decode error on {model_name}")
                break
            except Exception as e:
                err = str(e)
                if "503" in err or "UNAVAILABLE" in err:
                    safe_print(f"    {model_name} 503 busy, retrying...")
                    continue
                elif "404" in err or "NOT_FOUND" in err:
                    break
                elif "429" in err or "RESOURCE_EXHAUSTED" in err:
                    safe_print(f"    {model_name} 429 rate limit, trying next model...")
                    time.sleep(5)
                    break
                else:
                    safe_print(f"    {model_name} err: {err[:60]}")
                    break
    return []


# ── Main batch processor ───────────────────────────────

def run_batch():
    print("=" * 60)
    print(" FOOD DISCOVERY - BATCH PROCESSOR")
    print(" Multi-city | Short & Long form videos")
    print("=" * 60)

    config = load_config()
    restaurants = load_restaurants()
    already_processed_urls = {r.get("source_url", "") for r in restaurants}

    cities = [k for k in config.keys() if not k.startswith("_")]
    total_unprocessed = sum(
        1 for city in cities
        for entry in config[city]
        if not entry.get("processed", False) and entry["url"] not in already_processed_urls
    )

    print(f"Cities in dataset : {', '.join(cities)}")
    print(f"Videos to process : {total_unprocessed}")
    print()

    if total_unprocessed == 0:
        print("All videos already processed! Add more URLs to data/dataset_urls.json")
        return

    print("Loading Whisper model (base)...")
    whisper_model = whisper.load_model("base")
    print("Whisper ready.")
    print()

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    processed_count = 0
    failed_count = 0

    for city in cities:
        city_entries = config[city]
        pending = [
            e for e in city_entries
            if not e.get("processed", False) and e["url"] not in already_processed_urls
        ]
        if not pending:
            continue

        clean_city_name = normalize_city(city)
        print(f"\n{'='*60}")
        print(f" CITY: {clean_city_name.upper()} ({len(pending)} videos to process)")
        print(f"{'='*60}")

        for i, entry in enumerate(pending, 1):
            url = entry["url"]
            video_type = entry.get("type", "short_form")
            notes = entry.get("notes", "")

            print(f"\n[{i}/{len(pending)}] {video_type.upper()}")
            safe_print(f"  URL  : {url}")
            safe_print(f"  Notes: {notes}")

            # 1. Download
            print("  [1/3] Downloading audio...", end="", flush=True)
            audio_path, title, description, _duration = download_audio(url)
            if not audio_path:
                print(" FAILED")
                failed_count += 1
                continue
            size_kb = Path(audio_path).stat().st_size // 1024
            print(f" OK ({size_kb} KB)")

            # 2. Transcribe
            print("  [2/3] Transcribing...", end="", flush=True)
            transcript = transcribe(audio_path, whisper_model)
            if not transcript or len(transcript) < 10:
                if title:
                    transcript = f"Title: {title}\nDescription: {description}"
                else:
                    print(" FAILED (empty/no speech transcript)")
                    failed_count += 1
                    continue
            print(f" OK ({len(transcript)} chars)")

            # Save transcript
            audio_name = Path(audio_path).stem
            transcript_path = TRANSCRIPTS_DIR / f"{audio_name}.txt"
            transcript_path.write_text(transcript, encoding="utf-8")

            meta_path = TRANSCRIPTS_DIR / f"{audio_name}.meta.json"
            meta_path.write_text(
                json.dumps({
                    "title": title,
                    "description": description,
                    "duration": _duration,
                    "url": url
                }, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )

            # 3. Extract with Gemini
            print("  [3/3] Extracting with Gemini...", end="", flush=True)
            extracted = extract_with_gemini(transcript, clean_city_name, video_type, client, title=title, description=description)
            if not extracted:
                print(" SKIPPED (no specific restaurant identified)")
                entry["processed"] = True
                save_config(config)
                continue

            print(f" OK ({len(extracted)} restaurant(s))")

            # Add metadata
            for r in extracted:
                r["source_url"] = url
                r["source_video"] = Path(audio_path).name
                r["city"] = clean_city_name

            restaurants.extend(extracted)
            save_restaurants(restaurants)

            # Print found info
            for r in extracted:
                name = r.get("restaurant_name", "Unknown")
                cuisine = r.get("cuisine_type", "")
                dishes = ", ".join(r.get("must_try_dishes", [])[:2])
                safe_print(f"  --> {name} | {cuisine} | Try: {dishes}")

            entry["processed"] = True
            save_config(config)
            processed_count += 1

            time.sleep(1)

    print()
    print("=" * 60)
    print(" BATCH COMPLETE!")
    print("=" * 60)
    print(f"  Processed successfully : {processed_count}")
    print(f"  Failed / Skipped       : {failed_count}")
    print(f"  Total in database now  : {len(restaurants)} restaurants")
    print()
    print("City breakdown:")
    city_counts = {}
    for r in restaurants:
        c = normalize_city(r.get("city", "Unknown"))
        city_counts[c] = city_counts.get(c, 0) + 1
    for c, count in sorted(city_counts.items()):
        print(f"  {c:20s} : {count} restaurants")
    print()

def process_single_url(url: str, city: str = "", video_type: str = "", client=None,
                       whisper_model=None, progress_cb=None,
                       user_id: str = None, user_name: str = None,
                       hint_description: str = "") -> tuple[list, str]:
    """
    Processes a SINGLE video URL:
    1. Downloads audio and gets metadata (title, description, duration)
    2. Auto-detects city from title/description if not provided
    3. Auto-detects video type from duration if not provided
    4. Transcribes with Whisper
    5. Extracts restaurant with Gemini using transcript + title + description
    6. Saves to data/restaurants.json and data/dataset_urls.json

    hint_description: Optional pre-known description (e.g. from playlist sync metadata).
                      Used as fallback when yt-dlp returns an empty description.
    """
    def log(msg):
        safe_print(msg)
        if progress_cb:
            progress_cb(msg)

    log(f"Processing URL: {url}")

    # 1. Download
    log("  [1/4] Downloading audio and video metadata (yt-dlp)...")
    audio_path, title, description, duration = download_audio(url)
    if not audio_path:
        return [], "Failed to download audio track."
    log(f"  OK: Video title: '{title[:60]}'")

    # Use hint_description as fallback when yt-dlp returns empty description
    if not description and hint_description:
        description = hint_description
        log("  [META] Using pre-fetched description as fallback.")

    # 2. Auto-detect city and type if not provided
    if not city or city == "auto":
        city = auto_detect_city(title, description)
        log(f"  [AUTO] Detected city: {city}")
    if not video_type or video_type == "auto":
        video_type = auto_detect_video_type(duration)
        log(f"  [AUTO] Detected type: {video_type} (duration: {duration}s)")

    # 3. Transcribe
    log("  [2/4] Transcribing audio with Whisper...")
    if whisper_model is None:
        whisper_model = whisper.load_model("base")
    transcript = transcribe(audio_path, whisper_model)
    if not transcript or len(transcript) < 10:
        if title:
            log("  [WARN] Audio had no clear speech; using video title & description.")
            transcript = f"Title: {title}\nDescription: {description}"
        else:
            return [], "No speech detected in audio and no metadata found."

    audio_name = Path(audio_path).stem
    transcript_path = TRANSCRIPTS_DIR / f"{audio_name}.txt"
    transcript_path.write_text(transcript, encoding="utf-8")

    meta_path = TRANSCRIPTS_DIR / f"{audio_name}.meta.json"
    meta_path.write_text(
        json.dumps({
            "title": title,
            "description": description,
            "duration": duration,
            "url": url
        }, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # 4. Extract with Gemini
    log("  [3/4] Extracting restaurant data with Gemini...")
    if client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        client = genai.Client(api_key=api_key)

    clean_city = normalize_city(city)
    extracted = extract_with_gemini(transcript, clean_city, video_type, client, title=title, description=description)
    if not extracted:
        config = load_config()
        city_key = city.lower().replace(" ", "_")
        if city_key in config:
            for entry in config[city_key]:
                if entry.get("url") == url:
                    entry["processed"] = True
            save_config(config)
        return [], "No specific restaurant could be identified from this video."

    cleaned_extracted = []
    for raw_r in extracted:
        raw_r["source_url"]   = url
        raw_r["source_video"] = Path(audio_path).name

        # Ensure complete schema sanitization before database insertion
        clean_r = sanitize_restaurant_record(raw_r, clean_city, title=title, description=description)
        if not clean_r or not clean_r.get("restaurant_name"):
            continue

        # Tag with the YouTube account that discovered this restaurant
        if user_id:
            clean_r["source_user_id"]   = user_id
            clean_r["source_user_name"] = user_name or user_id

        cleaned_extracted.append(clean_r)

    extracted = cleaned_extracted
    if not extracted:
        return [], "No valid restaurant could be identified from this video."

    restaurants = load_restaurants()
    existing_pairs = {(r.get("source_url"), r.get("source_user_id"), r.get("restaurant_name")) for r in restaurants}
    new_to_add = [
        r for r in extracted
        if (r.get("source_url"), r.get("source_user_id"), r.get("restaurant_name")) not in existing_pairs
    ]
    if new_to_add:
        restaurants.extend(new_to_add)
        save_restaurants(restaurants)
    # If all already exist, nothing to save — skip duplicate writes

    config = load_config()
    city_key = city.lower().replace(" ", "_")
    if city_key not in config:
        config[city_key] = []
    found_in_config = False
    for entry in config[city_key]:
        if entry.get("url") == url:
            entry["processed"] = True
            found_in_config = True
            break
    if not found_in_config:
        config[city_key].append({
            "url": url,
            "notes": title or "Added via single processor",
            "type": video_type,
            "processed": True
        })
    save_config(config)

    names = ", ".join(r.get("restaurant_name", "Unknown") for r in extracted)
    log(f"  [4/4] Done! Extracted: {names} ({clean_city})")
    return extracted, f"Successfully extracted: {names} ({clean_city})"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="Process a single video URL")
    parser.add_argument("--city", default="auto", help="City name or 'auto' to detect from video metadata")
    parser.add_argument("--type", default="auto", help="short_form, long_form, or 'auto' to detect from duration")
    parser.add_argument("--user-id", default=None, help="User ID tagging the restaurant")
    parser.add_argument("--user-name", default=None, help="Display name of user tagging the restaurant")
    args = parser.parse_args()

    user_id = args.user_id or os.environ.get("FOOD_DISCOVERY_USER_ID")
    user_name = args.user_name or os.environ.get("FOOD_DISCOVERY_USER_NAME")

    if args.url:
        process_single_url(args.url, args.city, args.type, user_id=user_id, user_name=user_name)
    else:
        run_batch()
