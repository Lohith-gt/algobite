"""
YouTube Account & Playlist Sync Engine
======================================
Connects directly to a user's Google account or YouTube playlist,
retrieves food review videos, processes them with Whisper + Gemini,
and associates the extracted restaurants with that specific user account.

Key Features:
  1. Google OAuth 2.0 Flow:
     - Connect via official Google consent screen
     - Access user's YouTube playlists (Food, Watch Later, etc.)
     - Authenticates user email / identity
  2. Direct Playlist Link & ID Support (Zero-Setup Fallback):
     - Extract videos from any YouTube food playlist via yt-dlp
     - Assign to custom user account names (e.g. Account A, Account B)
  3. Multi-User Separation:
     - Maintains connected accounts registry in data/connected_accounts.json
     - Tags all extracted restaurants with source_user_id and source_user_name
     - Enables account-specific food suggestions
"""

import os
import sys
import json
import time
import re
from pathlib import Path
from typing import Optional, List, Dict, Any

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DATA_DIR = Path(__file__).parent.parent / "data"
TOKENS_DIR = DATA_DIR / "tokens"
TOKENS_DIR.mkdir(parents=True, exist_ok=True)

ACCOUNTS_FILE = DATA_DIR / "connected_accounts.json"
CLIENT_SECRETS_FILE = Path(__file__).parent.parent / "client_secret.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid"
]


# ── Account Registry Functions ────────────────────────────────

def load_connected_accounts() -> Dict[str, Dict[str, Any]]:
    """Loads all connected accounts from JSON."""
    if ACCOUNTS_FILE.exists():
        try:
            return json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_connected_accounts(accounts: Dict[str, Dict[str, Any]]):
    """Saves connected accounts to JSON."""
    ACCOUNTS_FILE.write_text(
        json.dumps(accounts, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def register_or_update_account(
    user_id: str,
    user_name: str,
    email: str = "",
    playlist_id: str = "",
    playlist_name: str = "",
    synced_video_count: int = 0
) -> Dict[str, Any]:
    """Registers a new account or updates an existing account's playlist details."""
    accounts = load_connected_accounts()
    clean_id = user_id.lower().replace(" ", "_")[:50]

    record = accounts.get(clean_id, {
        "user_id": clean_id,
        "user_name": user_name,
        "email": email or user_name,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "playlists": []
    })

    record["user_name"] = user_name
    if email:
        record["email"] = email
    record["last_synced"] = time.strftime("%Y-%m-%d %H:%M:%S")

    if playlist_id:
        existing = next((p for p in record.get("playlists", []) if p.get("id") == playlist_id), None)
        if existing:
            existing["name"] = playlist_name or existing.get("name", "Playlist")
            existing["video_count"] = synced_video_count
            existing["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        else:
            if "playlists" not in record:
                record["playlists"] = []
            record["playlists"].append({
                "id": playlist_id,
                "name": playlist_name or "Food Playlist",
                "video_count": synced_video_count,
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")
            })

    accounts[clean_id] = record
    save_connected_accounts(accounts)
    return record


# ── YouTube Data API v3 OAuth Flow ────────────────────────────

def is_google_oauth_configured() -> bool:
    """Checks if client_secret.json or env vars are configured."""
    if CLIENT_SECRETS_FILE.exists():
        return True
    if os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"):
        return True
    return False


def get_oauth_flow():
    """Builds an InstalledAppFlow instance for Google OAuth."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if CLIENT_SECRETS_FILE.exists():
        return InstalledAppFlow.from_client_secrets_file(
            str(CLIENT_SECRETS_FILE),
            scopes=SCOPES
        )
    elif os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"):
        client_config = {
            "installed": {
                "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost:8080/", "http://localhost:8501/"]
            }
        }
        return InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    else:
        raise ValueError(
            "Google OAuth is not configured. Place 'client_secret.json' in project root "
            "or set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your .env file."
        )


def authenticate_google_account() -> Dict[str, Any]:
    """
    Launches the Google OAuth login window in the default browser.
    Returns user details (email, name, credentials token path).
    """
    from googleapiclient.discovery import build
    import google.auth.transport.requests

    flow = get_oauth_flow()
    # Runs a local webserver on port 8080 to receive OAuth callback
    credentials = flow.run_local_server(
        port=8080,
        prompt="consent",
        access_type="offline"
    )

    # Fetch user profile (email and name)
    oauth2_client = build("oauth2", "v2", credentials=credentials)
    user_info = oauth2_client.userinfo().get().execute()

    email = user_info.get("email", "")
    name = user_info.get("name", email.split("@")[0] if email else "Google User")
    user_id = email.lower().replace("@", "_at_").replace(".", "_")

    # Save credentials token
    token_file = TOKENS_DIR / f"{user_id}.json"
    token_data = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes
    }
    token_file.write_text(json.dumps(token_data, indent=2), encoding="utf-8")

    # Register in connected accounts
    account_record = register_or_update_account(
        user_id=user_id,
        user_name=name,
        email=email
    )

    return {
        "user_id": user_id,
        "user_name": name,
        "email": email,
        "account_record": account_record
    }


def get_user_youtube_playlists(user_id: str) -> List[Dict[str, str]]:
    """
    Fetches all playlists belonging to the authenticated Google account.
    """
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_file = TOKENS_DIR / f"{user_id}.json"
    if not token_file.exists():
        return []

    token_data = json.loads(token_file.read_text(encoding="utf-8"))
    credentials = Credentials.from_authorized_user_info(token_data, scopes=SCOPES)

    youtube = build("youtube", "v3", credentials=credentials)

    playlists = []
    request = youtube.playlists().list(
        part="snippet,contentDetails",
        mine=True,
        maxResults=50
    )

    while request:
        response = request.execute()
        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            details = item.get("contentDetails", {})
            playlists.append({
                "id": item.get("id"),
                "title": snippet.get("title", "Untitled"),
                "description": snippet.get("description", ""),
                "item_count": details.get("itemCount", 0),
                "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url", "")
            })
        request = youtube.playlists().list_next(request, response)

    return playlists


def fetch_playlist_videos_via_api(user_id: str, playlist_id: str) -> List[Dict[str, str]]:
    """
    Fetches all video URLs from a playlist using YouTube Data API.
    """
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_file = TOKENS_DIR / f"{user_id}.json"
    if not token_file.exists():
        return []

    token_data = json.loads(token_file.read_text(encoding="utf-8"))
    credentials = Credentials.from_authorized_user_info(token_data, scopes=SCOPES)

    youtube = build("youtube", "v3", credentials=credentials)

    videos = []
    request = youtube.playlistItems().list(
        part="snippet",
        playlistId=playlist_id,
        maxResults=50
    )

    while request:
        response = request.execute()
        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            vid = snippet.get("resourceId", {}).get("videoId")
            title = snippet.get("title", "")
            if vid and title != "Private video" and title != "Deleted video":
                videos.append({
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "title": title,
                    "video_id": vid
                })
        request = youtube.playlistItems().list_next(request, response)

    return videos


# ── Direct yt-dlp Playlist Extraction (No API Key Required) ───

def normalize_playlist_url(raw: str) -> str:
    """
    Normalizes any YouTube playlist reference into the canonical playlist URL.
    Handles:
      - https://www.youtube.com/watch?v=...&list=PL...
      - https://www.youtube.com/playlist?list=PL...
      - https://youtu.be/...list=PL...
      - PL... (raw playlist ID)
      - WL (Watch Later ID)
    """
    raw = raw.strip()
    match = re.search(r"[?&]list=([a-zA-Z0-9_-]+)", raw)
    if match:
        return f"https://www.youtube.com/playlist?list={match.group(1)}"
    if not raw.startswith("http"):
        return f"https://www.youtube.com/playlist?list={raw}"
    return raw


def extract_playlist_videos_ytdlp(playlist_url_or_id: str) -> tuple[str, List[Dict[str, str]]]:
    """
    Extracts all video URLs from any public or unlisted YouTube playlist
    using yt-dlp flat extraction. Fast and requires no Google API setup.

    Returns: (playlist_title, list of { url, title, description, video_id })
    """

    import yt_dlp

    url = normalize_playlist_url(playlist_url_or_id)

    ydl_opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info:
            return "Unknown Playlist", []

        playlist_title = info.get("title", "YouTube Playlist")
        entries = info.get("entries")

        videos = []
        if entries:
            for e in entries:
                if not e:
                    continue
                vid = e.get("id") or e.get("url")
                vtitle = e.get("title") or "Video"
                vdesc = e.get("description") or ""  # Description — often has restaurant name & address
                if vid:
                    clean_url = f"https://www.youtube.com/watch?v={vid}" if not str(vid).startswith("http") else str(vid)
                    videos.append({
                        "url": clean_url,
                        "title": vtitle,
                        "description": vdesc,
                        "video_id": str(vid).split("=")[-1] if "=" in str(vid) else str(vid).split("/")[-1]
                    })
        elif info.get("id"):
            # Single video fallback if a standalone video URL was provided
            vid = info.get("id")
            vtitle = info.get("title") or "Video"
            vdesc = info.get("description") or ""
            clean_url = f"https://www.youtube.com/watch?v={vid}"
            videos.append({
                "url": clean_url,
                "title": vtitle,
                "description": vdesc,
                "video_id": str(vid)
            })
            playlist_title = vtitle

        return playlist_title, videos



# ── Sync & Ingestion Pipeline ─────────────────────────────────

def sync_videos_to_backend(
    videos: List[Dict[str, str]],
    user_id: str,
    user_name: str,
    playlist_name: str = ""
) -> Dict[str, Any]:
    """
    Sends the list of playlist videos to the local ingestion API (http://localhost:8000/api/batch_ingest).
    If the API server is offline, directly calls process_single_url sequentially.
    """
    import requests

    backend_url = "http://127.0.0.1:8000/api/batch_ingest"
    payload = {
        "videos": videos,
        "user_id": user_id,
        "user_name": user_name,
        "playlist_name": playlist_name or "Food Playlist"
    }

    try:
        res = requests.post(backend_url, json=payload, timeout=5)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass

    # Fallback: process directly via batch_process
    from batch_process import process_single_url, load_restaurants

    existing = {r.get("source_url") for r in load_restaurants()}
    queued = 0
    skipped = 0

    for v in videos:
        u = v["url"]
        if u in existing:
            skipped += 1
            continue
        process_single_url(
            url=u,
            city="auto",
            video_type="auto",
            user_id=user_id,
            user_name=user_name,
            hint_description=v.get("description", ""),
        )
        queued += 1

    return {
        "queued": queued,
        "skipped": skipped,
        "message": f"Processed {queued} new videos, {skipped} already existed.",
        "user_id": user_id
    }


# ── Strict User Authentication & Privacy ──────────────────────

USERS_FILE = DATA_DIR / "users.json"


def load_users() -> Dict[str, Dict[str, Any]]:
    """Loads all registered users."""
    if USERS_FILE.exists():
        try:
            return json.loads(USERS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_users(users: Dict[str, Dict[str, Any]]):
    """Saves users to data/users.json."""
    USERS_FILE.write_text(
        json.dumps(users, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """Hashes a password with a cryptographic salt using SHA-256."""
    import hashlib
    import secrets

    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}{password}".encode("utf-8")).hexdigest()
    return hashed, salt


def register_user(username_or_email: str, password: str, display_name: str = "") -> tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Registers a new private user account.
    Returns: (success, message, user_dict)
    """
    clean_input = username_or_email.strip().lower()
    if not clean_input:
        return False, "Username or Email cannot be empty.", None
    if len(password) < 4:
        return False, "Password must be at least 4 characters long.", None

    user_id = clean_input.replace("@", "_at_").replace(".", "_").replace(" ", "_")[:50]
    users = load_users()

    if user_id in users:
        return False, f"An account with this username or email already exists. Please log in.", None

    pwd_hash, salt = hash_password(password)
    user_record = {
        "user_id": user_id,
        "username": clean_input,
        "display_name": display_name.strip() or clean_input.split("@")[0].capitalize(),
        "password_hash": pwd_hash,
        "salt": salt,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "linked_playlists": []
    }

    users[user_id] = user_record
    save_users(users)
    return True, "Account created successfully!", user_record


def login_user(username_or_email: str, password: str) -> tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Verifies user credentials.
    Returns: (success, message, user_dict)
    """
    clean_input = username_or_email.strip().lower()
    user_id = clean_input.replace("@", "_at_").replace(".", "_").replace(" ", "_")[:50]
    users = load_users()

    user = users.get(user_id)
    if not user:
        return False, "No account found with this username or email.", None

    pwd_hash, salt = user.get("password_hash"), user.get("salt")
    if not pwd_hash or not salt:
        return False, "Account error. Please contact administrator.", None

    check_hash, _ = hash_password(password, salt=salt)
    if check_hash != pwd_hash:
        return False, "Incorrect password. Please try again.", None

    return True, "Login successful!", user


def link_user_playlist(user_id: str, playlist_url_or_id: str, playlist_name: str = "", initial_video_ids: List[str] = None) -> Dict[str, Any]:
    """
    Attaches a YouTube food playlist to a user account with auto-sync enabled.
    """
    users = load_users()
    user = users.get(user_id)
    if not user:
        # Create minimal user if not registered yet
        user = {
            "user_id": user_id,
            "username": user_id,
            "display_name": user_id.capitalize(),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "linked_playlists": []
        }
        users[user_id] = user

    playlists = user.setdefault("linked_playlists", [])
    clean_id = playlist_url_or_id.strip()

    existing = next((p for p in playlists if p.get("id") == clean_id or p.get("url") == clean_id), None)
    if existing:
        existing["name"] = playlist_name or existing.get("name", "Food Playlist")
        existing["auto_sync"] = True
        existing["last_synced"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if initial_video_ids:
            known = set(existing.get("known_video_ids", []))
            known.update(initial_video_ids)
            existing["known_video_ids"] = list(known)
    else:
        playlists.append({
            "id": clean_id,
            "url": clean_id,
            "name": playlist_name or "Food Playlist",
            "auto_sync": True,
            "last_synced": time.strftime("%Y-%m-%d %H:%M:%S"),
            "known_video_ids": list(set(initial_video_ids or []))
        })

    save_users(users)
    return user


# ── Automatic Background Syncing Engine ───────────────────────

def auto_sync_user_playlists(user_id: str) -> int:
    """
    Checks all linked playlists for a specific user.
    If any newly added videos are detected, sends them to the pipeline immediately!
    Returns number of newly queued videos.
    """
    users = load_users()
    user = users.get(user_id)
    if not user:
        return 0

    user_name = user.get("display_name", user_id)
    playlists = user.get("linked_playlists", [])
    total_new = 0
    any_checked = False

    for pl in playlists:
        if not pl.get("auto_sync", True):
            continue

        pl_url = pl.get("url") or pl.get("id")
        if not pl_url:
            continue
        known_ids = set(pl.get("known_video_ids", []))

        try:
            pl_title, live_videos = extract_playlist_videos_ytdlp(pl_url)
            new_videos = [v for v in live_videos if v.get("video_id") not in known_ids]

            # Always update last_synced so UI shows current check time
            pl["last_synced"] = time.strftime("%Y-%m-%d %H:%M:%S")
            any_checked = True

            if new_videos:
                print(f"[AUTO-SYNC] Found {len(new_videos)} NEW video(s) in playlist '{pl_title}' for user '{user_name}'!")
                for idx, v in enumerate(new_videos, 1):
                    vid = v.get("video_id")
                    vtitle = v.get("title", "Video")
                    print(f"[AUTO-SYNC] ({idx}/{len(new_videos)}) Ingesting: {vtitle} [{vid}]")
                    try:
                        sync_videos_to_backend(
                            videos=[v],
                            user_id=user_id,
                            user_name=user_name,
                            playlist_name=pl_title
                        )
                        known_ids.add(vid)
                        pl["known_video_ids"] = list(known_ids)
                        pl["last_synced"] = time.strftime("%Y-%m-%d %H:%M:%S")
                        save_users(users)
                        total_new += 1
                    except Exception as ve:
                        print(f"[AUTO-SYNC ERROR] Failed video {vid}: {ve}")
            else:
                print(f"[AUTO-SYNC] Playlist '{pl_title}' is up to date ({len(known_ids)} known videos).")
        except Exception as e:
            print(f"[AUTO-SYNC ERROR] Failed checking playlist {pl_url}: {e}")

    if any_checked:
        save_users(users)

    return total_new


def auto_sync_all_users() -> Dict[str, int]:
    # Runs an auto-sync check across all registered user playlists.
    users = load_users()

    results = {}
    for uid in users:
        new_vids = auto_sync_user_playlists(uid)
        if new_vids > 0:
            results[uid] = new_vids
    return results


_daemon_started = False

def start_auto_sync_daemon(interval_seconds: int = 60):
    # Starts a background daemon thread that periodically checks user playlists
    # and automatically ingests new videos into their databases.
    global _daemon_started

    if _daemon_started:
        return
    _daemon_started = True

    import threading

    def _sync_worker():
        while True:
            time.sleep(interval_seconds)
            try:
                auto_sync_all_users()
            except Exception as e:
                print(f"[AUTO-SYNC DAEMON] Error in worker loop: {e}")

    worker_thread = threading.Thread(target=_sync_worker, daemon=True, name="PlaylistAutoSyncWorker")
    worker_thread.start()
    print(f"[AUTO-SYNC] Background playlist auto-sync worker started (interval: {interval_seconds}s).")

