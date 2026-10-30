"""
Food Discovery Assistant — Flask Web Server
============================================
Replaces the Streamlit app with a pure Flask + HTML frontend.

Run with:
    python server.py
    OR
    venv\\Scripts\\python.exe server.py

API Endpoints:
    GET  /                     → Serve the SPA HTML (templates/index.html)
    GET  /api/restaurants      → Return all restaurants as JSON
    GET  /api/cities           → Return list of unique cities
    POST /api/search           → Run travel filter + AI suggestion
    POST /api/add_video        → Process a single YouTube URL via batch_process
    POST /api/link_playlist    → Link/sync a YouTube playlist
    POST /api/auth/login       → Simple credential login
    POST /api/auth/register    → Register a new local account
"""

import os
import sys
import json
import time
import subprocess
import hashlib
import bcrypt
from pathlib import Path

# ── Encoding fix (must be before any import that touches stdout) ──
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from flask import Flask, request, jsonify, render_template, session

# ── Path Setup ────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
SRC_DIR  = BASE_DIR / "src"
DATA_DIR = BASE_DIR / "data"
RESTAURANTS_DB  = DATA_DIR / "restaurants.json"
USERS_DB        = DATA_DIR / "users.json"

sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(SRC_DIR))

# ── Flask App ─────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = "food_discovery_secret_2024"


# ── Helpers ───────────────────────────────────────────────────────

def load_restaurants() -> list:
    """Load the restaurant database from disk."""
    if not RESTAURANTS_DB.exists():
        return []
    try:
        with open(RESTAURANTS_DB, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def load_users() -> dict:
    """Load local user accounts."""
    if not USERS_DB.exists():
        return {}
    try:
        return json.loads(USERS_DB.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_users(users: dict):
    """Persist local user accounts."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    USERS_DB.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")


def hash_pw(pw: str) -> str:
    """Hash a password with bcrypt (returns a utf-8 string)."""
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def check_pw(pw: str, stored_hash: str, salt: str = None) -> bool:
    """
    Verify a password against a stored hash.
    Supports both:
    - Legacy SHA-256 hex strings (with or without salt)
    - bcrypt hashes (starts with '$2b$' or '$2a$')
    """
    if stored_hash.startswith("$2"):
        # bcrypt hash
        try:
            return bcrypt.checkpw(pw.encode("utf-8"), stored_hash.encode("utf-8"))
        except Exception:
            return False
    else:
        # Legacy SHA-256 — compare with or without salt
        if salt:
            return hashlib.sha256(f"{salt}{pw}".encode("utf-8")).hexdigest() == stored_hash
        return hashlib.sha256(pw.encode()).hexdigest() == stored_hash


def generate_gemini_fallback(restaurants, location, city, arrival_time, available_hours, preferences, dining_minutes):
    """
    Direct Gemini generation with quota-resilient model fallback (including flash-lite).
    Used when primary flash models hit daily free-tier rate limits.
    """
    try:
        from google import genai
        from dotenv import load_dotenv
        load_dotenv(BASE_DIR / ".env")
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None

        client = genai.Client(api_key=api_key)
        restaurants_text = json.dumps(restaurants, indent=2, ensure_ascii=False)

        prompt = f"""
You are a knowledgeable local food guide who knows {city} very well.

The user is currently at: {location}
Current time: {arrival_time}
Available time: {available_hours} hours total (with {dining_minutes} min reserved for dining)
Special preferences: {preferences if preferences else "None specified"}

REAL TRAVEL & RESTAURANT DATA:
Each restaurant below has been pre-filtered and enriched with actual road travel data:
- Road travel time and distance from {location} ("distance_km", "travel_minutes_one_way", "total_time_minutes")
- Google Maps search link ("google_maps_link") and turn-by-turn directions link ("google_maps_directions")
- Estimated crowd level at arrival ("crowd_at_arrival")
- Opening hours status ("opening_status")

{restaurants_text}

Based on this information, recommend the BEST 1-2 restaurants for this user.
CRITICAL — PROXIMITY FIRST:
1. The user is at "{location}". Strongly prioritize restaurants physically closest to {location} (lowest distance_km).
   NEVER bypass a nearby restaurant (within 0–2 km) to recommend a far-away place (5–10+ km) across town unless user requested it!
2. Places that are open at {arrival_time}
3. Lower travel times (travel_minutes_one_way)
4. Matching food preferences

Format your response in clean Markdown with:
## 🍽️ Recommended for You

### 1. [Restaurant Name]
- **Why I'm recommending this**: [Clear explanation referencing opening status, travel time, crowd level, and dishes]
- **What to Order**: [Must-try dishes]
- **Travel**: [X km away, ~Y min drive each way]
- **Status & Crowd**: [Opening status emoji/label and crowd level]
- **Directions**: [Clickable Markdown link to Google Maps directions]

### 2. [Backup Option] (if a second feasible place exists)
[Same format as above]
"""

        LITE_MODELS = [
            "gemini-3.1-flash-lite",
            "gemini-flash-lite-latest",
            "gemini-3.5-flash-lite",
            "gemini-3-flash-preview",
            "gemini-3.8-flash",
            "gemini-3.6-flash"
        ]

        for model_name in LITE_MODELS:
            try:
                res = client.models.generate_content(model=model_name, contents=prompt)
                if res and res.text:
                    return res.text.encode("utf-8", errors="replace").decode("utf-8")
            except Exception:
                continue
    except Exception as e:
        print(f"[FALLBACK ERROR] {e}")

    return None


# ══════════════════════════════════════════════════════════════════
# HTML ROUTE
# ══════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    """Serve the single-page application."""
    return render_template("index.html")


# ══════════════════════════════════════════════════════════════════
# API: RESTAURANTS
# ══════════════════════════════════════════════════════════════════

@app.route("/api/restaurants", methods=["GET"])
def api_restaurants():
    """
    Return restaurants as JSON.
    Query param:
        user_id (str): optional.
          - If provided and not 'guest'/'all': returns ONLY places saved by that user.
          - If 'guest': returns ONLY public/community restaurants.
          - If 'all': returns all restaurants.
    """
    try:
        user_id = request.args.get("user_id")
        restaurants = load_restaurants()

        if user_id == "all":
            filtered = restaurants
        elif user_id and user_id != "guest":
            filtered = [r for r in restaurants if r.get("source_user_id") == user_id]
        else:
            # Guest: show ALL restaurants (full community browse)
            filtered = restaurants

        return jsonify(filtered)
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/cities", methods=["GET"])
def api_cities():
    """Return the list of unique cities for the current user/guest."""
    try:
        user_id = request.args.get("user_id")
        restaurants = load_restaurants()

        if user_id == "all":
            filtered = restaurants
        elif user_id and user_id != "guest":
            user_data = [r for r in restaurants if r.get("source_user_id") == user_id]
            filtered = user_data if user_data else restaurants
        else:
            # Guest: show cities from ALL restaurants
            filtered = restaurants

        cities = sorted(set(
            r.get("city", "").strip()
            for r in filtered
            if r.get("city", "").strip()
        ))
        return jsonify(cities)
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════════
# API: SEARCH  (the main AI query endpoint)
# ══════════════════════════════════════════════════════════════════

@app.route("/api/search", methods=["POST"])
def api_search():
    """
    Body (JSON):
        location        str  — user's current location (e.g. "Bengaluru Railway Station")
        city            str  — city name
        arrival_time    str  — HH:MM or "2:00 PM"
        available_hours float
        preferences     str  — dietary / other preferences
        dining_minutes  int  — default 40
        user_id         str  — optional; filter by saved playlist
    Returns:
        { suggestion: str (markdown), restaurants: [...] }
    """
    try:
        data = request.get_json(force=True) or {}

        location        = data.get("location", "").strip()
        city            = data.get("city", "").strip()
        arrival_time    = data.get("arrival_time", "").strip()
        available_hours = float(data.get("available_hours", 2.0))
        preferences     = data.get("preferences", "").strip()
        dining_minutes  = int(data.get("dining_minutes", 40))
        user_id         = data.get("user_id", None) or None

        if not location or not city:
            return jsonify({"ok": False, "message": "location and city are required."}), 400

        # Convert HH:MM → "H:MM AM/PM" if needed
        if arrival_time and ":" in arrival_time and len(arrival_time) <= 5:
            try:
                h, m = map(int, arrival_time.split(":"))
                period = "AM" if h < 12 else "PM"
                h12 = h % 12 or 12
                arrival_time = f"{h12}:{m:02d} {period}"
            except Exception:
                pass

        if not arrival_time:
            from datetime import datetime
            now = datetime.now()
            period = "AM" if now.hour < 12 else "PM"
            h12 = now.hour % 12 or 12
            arrival_time = f"{h12}:{now.minute:02d} {period}"

        # ── Import backend modules ────────────────────────────────
        from step5_suggester import get_food_suggestion
        from step6_router import (
            filter_restaurants_by_travel_time,
            geocode_user_location,
            geocode_restaurant,
        )
        from step7_crowd import enrich_restaurants_with_crowd_and_maps
        from step8_hours import enrich_restaurants_with_hours

        # ── Load + filter restaurants ─────────────────────────────
        all_restaurants = load_restaurants()
        if not all_restaurants:
            return jsonify({"ok": False, "message": "No restaurant data available. Process some videos first!"}), 400

        # Filter by user if specified
        if user_id and user_id != "guest":
            all_restaurants = [r for r in all_restaurants if r.get("source_user_id") == user_id]
        else:
            all_restaurants = [r for r in all_restaurants if not r.get("source_user_id")]

        # City filter (loose match)
        city_lower = (city or "").lower()
        city_restaurants = [
            r for r in all_restaurants
            if city_lower in (r.get("city") or "").lower()
            or (r.get("city") or "").lower() in city_lower
        ]

        if not city_restaurants:
            return jsonify({
                "ok": False,
                "message": f"No restaurants found for '{city}' in the database."
            }), 404

        # ── Phase 2: Travel filtering ─────────────────────────────
        city_restaurants = filter_restaurants_by_travel_time(
            restaurants=city_restaurants,
            user_location_str=location,
            city=city,
            available_hours=available_hours,
            dining_minutes=dining_minutes
        )

        # ── Phase 2.1: Crowd + Maps links ─────────────────────────
        city_restaurants = enrich_restaurants_with_crowd_and_maps(
            city_restaurants,
            arrival_time_str=arrival_time,
            user_location=location,
            user_city=city
        )

        # ── Phase 5: Opening hours ────────────────────────────────
        city_restaurants = enrich_restaurants_with_hours(
            city_restaurants,
            arrival_time_str=arrival_time,
        )

        # ── Add lat/lon for map markers ───────────────────────────
        user_lat, user_lon = geocode_user_location(location, city)
        for r in city_restaurants:
            try:
                r_lat, r_lon = geocode_restaurant(r)
                r["_lat"] = r_lat
                r["_lon"] = r_lon
            except Exception:
                r["_lat"] = None
                r["_lon"] = None

        # ── AI suggestion ─────────────────────────────────────────
        # Pass the pre-routed and enriched city_restaurants directly with actual distances
        suggestion = get_food_suggestion(
            current_location=location,
            city=city,
            arrival_time=arrival_time,
            available_hours=available_hours,
            preferences=preferences,
            use_routing=True,
            dining_minutes=dining_minutes,
            user_id=user_id if (user_id and user_id != "guest") else None,
            pre_enriched_restaurants=city_restaurants
        )

        # Quota-resilient fallback: if primary models return an error or hit rate limit
        if not suggestion or suggestion.startswith("[ERROR]"):
            fallback = generate_gemini_fallback(
                restaurants=city_restaurants,
                location=location,
                city=city,
                arrival_time=arrival_time,
                available_hours=available_hours,
                preferences=preferences,
                dining_minutes=dining_minutes
            )
            if fallback:
                suggestion = fallback

        return jsonify({
            "ok": True,
            "suggestion": suggestion,
            "restaurants": city_restaurants,
            "user_location": {"lat": user_lat, "lon": user_lon},
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════════
# API: ADD VIDEO
# ══════════════════════════════════════════════════════════════════

@app.route("/api/add_video", methods=["POST"])
def api_add_video():
    """
    Body (JSON): { url, user_id, user_name }
    Runs batch_process.py as a subprocess.
    Returns: { ok, message }
    """
    try:
        data     = request.get_json(force=True) or {}
        url      = data.get("url", "").strip()
        user_id  = data.get("user_id", "guest")
        user_name = data.get("user_name", "Guest")

        if not url:
            return jsonify({"ok": False, "message": "No URL provided."}), 400

        python_exe = str(BASE_DIR / "venv" / "Scripts" / "python.exe")
        batch_script = str(BASE_DIR / "batch_process.py")

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["FOOD_DISCOVERY_USER_ID"]   = user_id
        env["FOOD_DISCOVERY_USER_NAME"] = user_name
        env["FOOD_DISCOVERY_VIDEO_URL"] = url

        result = subprocess.run(
            [python_exe, batch_script, "--url", url,
             "--user-id", user_id, "--user-name", user_name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            cwd=str(BASE_DIR),
            env=env
        )

        if result.returncode == 0:
            return jsonify({
                "ok": True,
                "message": "Video processed successfully!",
                "log": (result.stdout or "") + (result.stderr or "")
            })
        else:
            return jsonify({
                "ok": False,
                "message": "Processing failed. Check the log for details.",
                "log": (result.stdout or "") + (result.stderr or "")
            }), 500

    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "message": "Processing timed out (>5 min). The video may still be processing."}), 500
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════════
# API: LINK PLAYLIST
# ══════════════════════════════════════════════════════════════════

@app.route("/api/link_playlist", methods=["POST"])
def api_link_playlist():
    """
    Body (JSON): { playlist_url, user_id, user_name }
    Extracts playlist videos via yt-dlp, links them to the user account,
    then syncs to the backend ingestion pipeline.
    Returns: { ok, count, title, message }
    """
    try:
        data         = request.get_json(force=True) or {}
        playlist_url = data.get("playlist_url", "").strip()
        user_id      = data.get("user_id", "guest")
        user_name    = data.get("user_name", "Guest")

        if not playlist_url:
            return jsonify({"ok": False, "message": "No playlist URL provided."}), 400

        from youtube_account_sync import (
            extract_playlist_videos_ytdlp,
            link_user_playlist,
            sync_videos_to_backend,
        )

        # Step 1: Extract video list
        playlist_title, videos = extract_playlist_videos_ytdlp(playlist_url)
        if not videos:
            return jsonify({"ok": False, "message": "No videos found in this playlist. Check the URL."}), 400

        # Step 2: Link playlist to user account
        video_ids = [v.get("video_id") or v.get("id") for v in videos if (v.get("video_id") or v.get("id"))]
        link_user_playlist(user_id, playlist_url, playlist_title, video_ids)

        # Step 3: Sync / ingest videos in background thread to prevent HTTP timeouts
        import threading
        sync_thread = threading.Thread(
            target=sync_videos_to_backend,
            args=(videos, user_id, user_name, playlist_title),
            daemon=True
        )
        sync_thread.start()

        return jsonify({
            "ok": True,
            "count": len(videos),
            "title": playlist_title or "YouTube Playlist",
            "message": f"Successfully linked '{playlist_title or 'Food Playlist'}' ({len(videos)} videos). Ingestion has started in the background!",
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/user/playlists", methods=["GET"])
def api_user_playlists():
    """
    Return all linked playlists for the given user.
    Query param: user_id (str)
    """
    try:
        user_id = request.args.get("user_id") or session.get("user")
        if not user_id or user_id == "guest":
            return jsonify({"ok": True, "playlists": []})

        users = load_users()
        user = users.get(user_id) or users.get(user_id.lower())
        if not user:
            return jsonify({"ok": True, "playlists": []})

        playlists = user.get("linked_playlists", [])
        restaurants = load_restaurants()
        user_restaurants = [r for r in restaurants if r.get("source_user_id") == user_id]

        result = []
        for pl in playlists:
            raw_url = pl.get("url") or pl.get("id", "")
            known_ids = pl.get("known_video_ids", [])
            count = len(known_ids) if known_ids else len(user_restaurants)
            result.append({
                "id": pl.get("id", ""),
                "url": raw_url,
                "name": pl.get("name") or "Food Playlist",
                "last_synced": pl.get("last_synced", "Recently"),
                "auto_sync": pl.get("auto_sync", True),
                "video_count": count
            })

        return jsonify({"ok": True, "playlists": result})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/user/sync_playlists", methods=["POST"])
def api_user_sync_playlists():
    """
    Manually triggers an immediate background auto-sync check for user's playlists.
    Body (JSON): { user_id }
    """
    try:
        data = request.get_json(force=True) or {}
        user_id = data.get("user_id") or request.args.get("user_id") or session.get("user")
        if not user_id or user_id == "guest":
            return jsonify({"ok": False, "message": "Guest cannot sync playlists."}), 400

        from youtube_account_sync import auto_sync_user_playlists
        import threading

        sync_thread = threading.Thread(
            target=auto_sync_user_playlists,
            args=(user_id,),
            daemon=True,
            name=f"ManualSyncUser-{user_id}"
        )
        sync_thread.start()

        return jsonify({
            "ok": True,
            "message": "Playlist sync initiated in background! New videos are being transcribed & ingested."
        })
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


# Start background playlist auto-sync worker
try:
    from youtube_account_sync import start_auto_sync_daemon
    start_auto_sync_daemon(interval_seconds=60)
except Exception as _sync_err:
    print(f"[WARN] Auto-sync daemon could not start: {_sync_err}")


# ══════════════════════════════════════════════════════════════════
# API: AUTH
# ══════════════════════════════════════════════════════════════════

@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    """
    Body (JSON): { username, password }
    Returns: { ok, user: {username, display_name, user_id}, message }
    """
    try:
        data     = request.get_json(force=True) or {}
        username = data.get("username", "").strip().lower()
        password = data.get("password", "")

        if not username or not password:
            return jsonify({"ok": False, "message": "Username and password are required."}), 400

        users = load_users()
        if username not in users:
            return jsonify({"ok": False, "message": "User not found. Please register first."}), 404

        user = users[username]
        if not check_pw(password, user.get("password_hash", ""), user.get("salt")):
            return jsonify({"ok": False, "message": "Incorrect password."}), 401

        # Silently upgrade legacy SHA-256 hash to bcrypt on first login
        stored = user.get("password_hash", "")
        if stored and not stored.startswith("$2"):
            users[username]["password_hash"] = hash_pw(password)
            users[username].pop("salt", None)
            save_users(users)

        session["user"] = username
        return jsonify({
            "ok": True,
            "user": {
                "username": username,
                "display_name": user.get("display_name", username),
                "user_id": user.get("user_id", username),
            },
            "message": f"Welcome back, {user.get('display_name', username)}!"
        })

    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/auth/register", methods=["POST"])
def api_auth_register():
    """
    Body (JSON): { username, password, display_name }
    Returns: { ok, user, message }
    """
    try:
        data         = request.get_json(force=True) or {}
        username     = data.get("username", "").strip().lower()
        password     = data.get("password", "")
        display_name = data.get("display_name", username).strip()

        if not username or not password:
            return jsonify({"ok": False, "message": "Username and password are required."}), 400

        if len(username) < 3:
            return jsonify({"ok": False, "message": "Username must be at least 3 characters."}), 400

        if len(password) < 6:
            return jsonify({"ok": False, "message": "Password must be at least 6 characters."}), 400

        users = load_users()
        if username in users:
            return jsonify({"ok": False, "message": "Username already taken. Try signing in."}), 409

        users[username] = {
            "user_id": username,
            "username": username,
            "display_name": display_name or username,
            "password_hash": hash_pw(password),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        save_users(users)
        session["user"] = username

        return jsonify({
            "ok": True,
            "user": {
                "username": username,
                "display_name": display_name or username,
                "user_id": username,
            },
            "message": f"Account created! Welcome, {display_name or username}!"
        })

    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    session.pop("user", None)
    return jsonify({"ok": True, "message": "Signed out."})


# ══════════════════════════════════════════════════════════════════
# ERROR HANDLERS
# ══════════════════════════════════════════════════════════════════

@app.errorhandler(404)
def not_found(e):
    from flask import request as req
    # Return JSON for API routes, HTML for browser routes
    if req.path.startswith("/api/"):
        return jsonify({"ok": False, "message": "Endpoint not found.", "code": 404}), 404
    return render_template("404.html"), 404


@app.errorhandler(500)
def server_error(e):
    from flask import request as req
    if req.path.startswith("/api/"):
        return jsonify({"ok": False, "message": "Internal server error.", "code": 500}), 500
    return render_template("500.html"), 500


# ══════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  FOOD DISCOVERY ASSISTANT — Flask Server")
    print("=" * 60)
    print(f"  Base dir : {BASE_DIR}")
    print(f"  Data dir : {DATA_DIR}")
    print(f"  DB exists: {RESTAURANTS_DB.exists()}")
    print()
    print("  Open your browser at: http://localhost:5000")
    print("=" * 60)
    app.run(debug=True, host="0.0.0.0", port=5000, use_reloader=False)
