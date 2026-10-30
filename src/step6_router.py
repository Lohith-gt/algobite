"""
STEP 6: Live Distance & Travel Time Router (Phase 2)
=====================================================
Calculates REAL driving distances and travel times between
the user's location and each restaurant in the database.

HOW IT WORKS:
  1. Geocodes the user's location string → (lat, lon)
     using Nominatim (OpenStreetMap, FREE, no key needed)
  2. Geocodes each restaurant → (lat, lon)
     using restaurant name + area + city
  3. Queries the OSRM free public router for real road-based
     travel time between origin and each restaurant
  4. Applies time budget filter:
       Round-trip travel + dining time ≤ available hours
  5. Returns restaurants sorted by total time cost (closest first)

APIs Used (100% FREE, no credit card required):
  - Nominatim: https://nominatim.openstreetmap.org
  - OSRM:      https://router.project-osrm.org

WHY THIS MATTERS:
  Without routing, Gemini guesses distances from its training data.
  With routing, we filter restaurants mathematically BEFORE asking
  Gemini — so Gemini's recommendation is always time-feasible.
"""

import time
import requests
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

# ── Configuration ────────────────────────────────────────

# Nominatim requires a descriptive User-Agent (your app name/email)
NOMINATIM_USER_AGENT = "food_discovery_assistant_v1"

# OSRM public demo server (free, no key, may be slow under heavy load)
OSRM_BASE_URL = "https://router.project-osrm.org/route/v1/driving"

# Dining time budget to set aside for eating (minutes)
DEFAULT_DINING_MINUTES = 40

# How long to wait between Nominatim requests (respect rate limit: 1 req/sec)
NOMINATIM_DELAY = 1.1

# Driving speed fallback (km/h) if OSRM is unreachable
FALLBACK_SPEED_KMPH = 20  # conservative city speed

# ── Geocoding ────────────────────────────────────────────

_geolocator = None

# In-memory cache: query_string -> (lat, lon)
_geo_cache: dict[str, tuple] = {}

# Persistent cache file (saves across app restarts)
_CACHE_FILE = None

def _load_geocache():
    """Load geocache from disk into memory on first use."""
    global _geo_cache, _CACHE_FILE
    if _CACHE_FILE is not None:
        return
    try:
        from pathlib import Path
        import json
        _CACHE_FILE = Path(__file__).parent.parent / "data" / "geocache.json"
        if _CACHE_FILE.exists():
            raw = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            _geo_cache = {k: tuple(v) for k, v in raw.items()}
    except Exception:
        _CACHE_FILE = None

def _save_geocache():
    """Persist geocache to disk."""
    try:
        import json
        if _CACHE_FILE:
            _CACHE_FILE.write_text(
                json.dumps({k: list(v) for k, v in _geo_cache.items()}, indent=2),
                encoding="utf-8"
            )
    except Exception:
        pass


def _get_geolocator():
    """Returns a shared Nominatim geolocator instance."""
    global _geolocator
    if _geolocator is None:
        _geolocator = Nominatim(user_agent=NOMINATIM_USER_AGENT, timeout=10)
    return _geolocator


def geocode(query: str, retries: int = 2):
    """
    Converts a location string into GPS coordinates (latitude, longitude).
    Uses an in-memory + persistent file cache to avoid repeated Nominatim calls.

    Args:
        query: A human-readable location string.
               e.g. "Bengaluru Railway Station, Bengaluru, India"
               e.g. "Vidyarthi Bhavan, Basavangudi, Bengaluru, India"
    Returns:
        (latitude, longitude) tuple of floats, or (None, None) if not found.
    """
    _load_geocache()

    # Check cache first
    cache_key = query.strip().lower()
    if cache_key in _geo_cache:
        return _geo_cache[cache_key]

    geolocator = _get_geolocator()
    for attempt in range(retries):
        try:
            time.sleep(NOMINATIM_DELAY)  # Respect Nominatim rate limit
            location = geolocator.geocode(query, language="en")
            if location:
                result = (location.latitude, location.longitude)
                _geo_cache[cache_key] = result
                _save_geocache()
                return result
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            if attempt < retries - 1:
                time.sleep(3)
            else:
                print(f"   [GEO] Geocoding failed for '{query}': {e}")

    # Cache misses too, so we don't retry the same bad query
    _geo_cache[cache_key] = (None, None)
    _save_geocache()
    return None, None



def geocode_user_location(location_str: str, city: str):
    """
    Geocodes the user's starting point.

    Tries progressively broader queries until a result is found:
      1. Known transit hubs (e.g. Karimnagar bus stand -> TGSRTC Bus Station)
      2. "{location_str}, {city}, India"
      3. "{city} {location_str}, India"
      4. "{location_str}, {city}"
      5. "{city}, India" (last resort fallback to city center)

    Returns:
        (lat, lon) tuple or (None, None)
    """
    if not location_str or not city:
        return None, None

    city_clean = (city or "").strip().lower()
    loc_clean = (location_str or "").strip().lower()

    # Specific transit hubs and known landmarks where general OSM queries frequently
    # latch onto distant rural district stops instead of the city's main hub
    if city_clean == "karimnagar":
        bus_stand_keywords = [
            "bus stand", "busstand", "bus-stand", "bus station",
            "rtc bus stand", "tsrtc", "tgsrtc", "rtc", "bus stop"
        ]
        if any(kw in loc_clean for kw in bus_stand_keywords):
            # TGSRTC Bus Station, Karimnagar (18.4325638, 79.1294337)
            print(f"   [GEO] User location resolved to Karimnagar Bus Station -> (18.4326, 79.1294)")
            return 18.4325638, 79.1294337

    queries = [
        f"{location_str}, {city}, India",
        f"{city} {location_str}, India",
        f"{location_str}, {city}",
        f"{city}, India",  # city center fallback
    ]
    for q in queries:
        lat, lon = geocode(q)
        if lat:
            print(f"   [GEO] User location: '{q}' -> ({lat:.4f}, {lon:.4f})")
            return lat, lon
    print(f"   [GEO] Could not geocode user location: '{location_str}, {city}'")
    return None, None


def geocode_restaurant(restaurant: dict):
    """
    Geocodes a restaurant entry from the database.

    CRITICAL FOR MULTI-BRANCH RESTAURANTS:
    If a restaurant has a specified area/branch (e.g. 'RS Puram'):
      1. Uses already saved/verified coordinates if available.
      2. Tries exact full_address.
      3. Tries "Name, Area, City, India".
      4. Falls back to "Area, City, India" (neighborhood center).
      NEVER blindly falls back to "Name, City, India" without area verification,
      because multi-branch chains (like Social Kitchen) will otherwise latch onto
      whichever random branch (e.g. Kuniyamuthur) happens to be indexed in OpenStreetMap!

    Returns:
        (lat, lon) tuple or (None, None)
    """
    # 1. Use existing coordinates if already populated
    if restaurant.get("_lat") and restaurant.get("_lon"):
        return float(restaurant["_lat"]), float(restaurant["_lon"])
    coords = restaurant.get("verified_coords")
    if isinstance(coords, list) and len(coords) == 2 and coords[0] is not None and coords[1] is not None:
        return float(coords[0]), float(coords[1])

    name = restaurant.get("restaurant_name", "")
    city = restaurant.get("city", "")
    area = restaurant.get("area_or_locality") or ""
    full_addr = restaurant.get("full_address") or ""
    country = "Sweden" if (city or "").strip().lower() in ["stockholm", "gothenburg", "malmo", "sweden"] else "India"

    # 2. Try full address if available
    if full_addr:
        lat, lon = geocode(f"{full_addr}, {country}")
        if lat:
            restaurant["_lat"], restaurant["_lon"] = lat, lon
            return lat, lon

    # 3. Try restaurant name + specific branch area + city
    if area:
        lat, lon = geocode(f"{name}, {area}, {city}, {country}")
        if lat:
            restaurant["_lat"], restaurant["_lon"] = lat, lon
            return lat, lon

        # Try compound area sub-parts (e.g. "Tower Circle, Islam Masjid Road")
        import re
        subparts = [p.strip() for p in re.split(r'[,/|-]', area) if len(p.strip()) > 2]
        for part in subparts:
            lat, lon = geocode(f"{name}, {part}, {city}, {country}")
            if lat:
                restaurant["_lat"], restaurant["_lon"] = lat, lon
                return lat, lon
            lat, lon = geocode(f"{part}, {city}, {country}")
            if lat:
                print(f"   [GEO] '{name}': using sub-area '{part}' coords")
                restaurant["_lat"], restaurant["_lon"] = lat, lon
                return lat, lon

        # Fall back to the specific branch area/neighborhood center
        lat, lon = geocode(f"{area}, {city}, {country}")
        if lat:
            print(f"   [GEO] '{name}': using branch area '{area}' coords")
            restaurant["_lat"], restaurant["_lon"] = lat, lon
            return lat, lon

    # 4. Try restaurant name + city
    queries = [f"{name}, {city}, {country}", f"{name}, {city}"]
    for q in queries:
        lat, lon = geocode(q)
        if lat:
            restaurant["_lat"], restaurant["_lon"] = lat, lon
            return lat, lon

    # 5. Last-resort fallback to city center so distance is NEVER missing ('—')
    if city and city.strip().lower() not in ["unknown", ""]:
        for city_q in [f"{city}, {country}", city]:
            lat, lon = geocode(city_q)
            if lat:
                print(f"   [GEO] '{name}': using city center '{city}' fallback coords")
                restaurant["_lat"], restaurant["_lon"] = lat, lon
                return lat, lon

    return None, None


# ── OSRM Routing ─────────────────────────────────────────

def get_driving_time_osrm(
    origin_lat: float, origin_lon: float,
    dest_lat: float, dest_lon: float
) -> float | None:
    """
    Uses the OSRM (Open Source Routing Machine) free public API to
    calculate the real road-based driving time in minutes.

    OSRM URL format:
      /route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false

    Note: OSRM uses (lon, lat) order, NOT (lat, lon)!

    Returns:
        Travel time in minutes (float), or None if API is unreachable.
    """
    url = f"{OSRM_BASE_URL}/{origin_lon},{origin_lat};{dest_lon},{dest_lat}"
    params = {"overview": "false", "annotations": "false"}

    try:
        response = requests.get(url, params=params, timeout=8)
        if response.status_code == 200:
            data = response.json()
            if data.get("code") == "Ok":
                duration_seconds = data["routes"][0]["duration"]
                distance_meters = data["routes"][0]["distance"]
                travel_minutes = duration_seconds / 60
                distance_km = distance_meters / 1000
                return travel_minutes, distance_km
    except requests.exceptions.RequestException:
        pass
    return None, None


def haversine_distance_km(lat1, lon1, lat2, lon2) -> float:
    """
    Calculates straight-line distance between two GPS points using
    the Haversine formula. Used as a fallback when OSRM is unreachable.

    Returns distance in kilometers.
    """
    import math
    R = 6371  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# ── Main Filtering Function ───────────────────────────────

def filter_restaurants_by_travel_time(
    restaurants: list,
    user_location_str: str,
    city: str,
    available_hours: float,
    dining_minutes: int = DEFAULT_DINING_MINUTES
) -> list:
    """
    The main Phase 2 function. Filters + annotates restaurants with
    real travel data based on the user's time budget.

    Time Budget Formula:
        available_minutes = available_hours × 60
        feasible if: (2 × one_way_travel_mins) + dining_mins ≤ available_minutes

    Args:
        restaurants:        List of restaurant dicts from database.
        user_location_str:  User's current location (e.g., "Majestic").
        city:               City name (e.g., "Bengaluru").
        available_hours:    Total time available in hours (e.g., 2.0).
        dining_minutes:     Time to set aside for eating (default 40 min).

    Returns:
        List of restaurant dicts, each annotated with:
          - 'travel_minutes_one_way': float
          - 'distance_km': float
          - 'total_time_minutes': float  (round trip + dining)
          - 'is_feasible': bool
          - 'geo_note': explanation string
        Sorted by total_time_minutes (quickest first).
    """
    available_minutes = available_hours * 60
    time_for_travel = available_minutes - dining_minutes

    print(f"\n[ROUTE] Time Budget Calculation:")
    print(f"   Available total  : {available_minutes:.0f} min")
    print(f"   Reserved dining  : {dining_minutes} min")
    print(f"   Max round-trip   : {time_for_travel:.0f} min  ({time_for_travel/2:.0f} min each way)")

    # Step 1: Geocode the user's location
    print(f"\n[GEO] Geocoding user location: '{user_location_str}, {city}'")
    user_lat, user_lon = geocode_user_location(user_location_str, city)
    if not user_lat:
        print("   [WARN] Could not geocode user location. Skipping travel filter.")
        for r in restaurants:
            r["geo_note"] = "Travel data unavailable (user location not found)"
            r["is_feasible"] = True  # Don't block restaurants if we can't geocode
        return restaurants

    # Step 2: Geocode each restaurant & calculate travel time
    print(f"\n[ROUTE] Calculating distances to {len(restaurants)} restaurants...")
    annotated = []

    for r in restaurants:
        name = r.get("restaurant_name", "Unknown")
        r_city = r.get("city", city)

        # Geocode the restaurant
        r_lat, r_lon = geocode_restaurant(r)
        if not r_lat:
            print(f"   [SKIP] {name}: Could not geocode location")
            r["geo_note"] = "Location could not be determined on map"
            r["is_feasible"] = True  # Don't penalize if we just couldn't find it
            r["travel_minutes_one_way"] = None
            r["distance_km"] = None
            r["total_time_minutes"] = None
            annotated.append(r)
            continue

        # Get driving time from OSRM
        travel_min, dist_km = get_driving_time_osrm(user_lat, user_lon, r_lat, r_lon)

        if travel_min is None:
            # Fallback: estimate from straight-line distance
            straight_km = haversine_distance_km(user_lat, user_lon, r_lat, r_lon)
            dist_km = straight_km * 1.4  # road distance ≈ 1.4× straight line
            travel_min = (dist_km / FALLBACK_SPEED_KMPH) * 60
            geo_source = "estimated (OSRM unavailable)"
        else:
            geo_source = "OSRM road routing"

        round_trip_min = 2 * travel_min
        total_min = round_trip_min + dining_minutes
        is_feasible = total_min <= available_minutes

        r["travel_minutes_one_way"] = round(travel_min, 1)
        r["distance_km"] = round(dist_km, 2)
        r["total_time_minutes"] = round(total_min, 1)
        r["is_feasible"] = is_feasible

        status = "[OK] FEASIBLE" if is_feasible else "[!!] TOO FAR"
        r["geo_note"] = (
            f"{dist_km:.1f} km away | ~{travel_min:.0f} min one-way | "
            f"~{total_min:.0f} min total (travel + {dining_minutes} min dining) | {geo_source}"
        )

        print(
            f"   {status}  {name}: {dist_km:.1f} km, "
            f"{travel_min:.0f} min one-way, {total_min:.0f} min total"
        )
        annotated.append(r)

    # Step 3: Sort by total time (fastest first), feasible ones on top
    feasible = sorted(
        [r for r in annotated if r.get("is_feasible", True) and r.get("total_time_minutes") is not None],
        key=lambda r: r["total_time_minutes"]
    )
    infeasible = [r for r in annotated if not r.get("is_feasible", True)]
    unknown = [r for r in annotated if r.get("total_time_minutes") is None]

    print(f"\n[ROUTE] Result: {len(feasible)} feasible, {len(infeasible)} too far, {len(unknown)} location unknown")

    return feasible + unknown  # Return feasible + unknowns to Gemini; drop infeasible


# ── Quick standalone test ─────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    import json
    from pathlib import Path

    print("=" * 60)
    print("  PHASE 2: DISTANCE & ROUTING TEST")
    print("=" * 60)

    db_path = Path(__file__).parent.parent / "data" / "restaurants.json"
    with open(db_path, encoding="utf-8") as f:
        all_restaurants = json.load(f)

    # Filter to Bengaluru only
    bengaluru_restaurants = [r for r in all_restaurants if "bengaluru" in r.get("city", "").lower()]
    print(f"Testing with {len(bengaluru_restaurants)} Bengaluru restaurants\n")

    filtered = filter_restaurants_by_travel_time(
        restaurants=bengaluru_restaurants,
        user_location_str="Bengaluru Railway Station",
        city="Bengaluru",
        available_hours=2.0,
        dining_minutes=40
    )

    print("\n" + "=" * 60)
    print("FILTERED & RANKED RESTAURANTS (within time budget):")
    print("=" * 60)
    for i, r in enumerate(filtered, 1):
        name = r.get("restaurant_name")
        note = r.get("geo_note", "No routing data")
        print(f"{i}. {name}")
        print(f"   {note}")
