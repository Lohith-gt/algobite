"""
VIDEO FINDER
============
Searches YouTube directly for food review Shorts using yt-dlp's search feature.
No need to manually find URLs — this script finds real, working videos for you!

HOW IT WORKS:
- yt-dlp can search YouTube just like a browser
- We search for "[city] food review" and filter for Shorts (< 3 min)
- Found URLs are saved to data/dataset_urls.json automatically
- Then run batch_process.py to process them all

USAGE:
  python find_videos.py

You can customize the search queries below.
"""

import sys, os, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
import yt_dlp

DATASET_CONFIG = Path("data/dataset_urls.json")

# ── Search queries per city ────────────────────────────
# You can add, edit or remove any of these
SEARCH_CONFIG = {
    "bengaluru": [
        "bengaluru street food short",
        "bangalore food review shorts",
        "bengaluru restaurant hidden gem short",
        "bangalore food vlog short",
    ],
    "coimbatore": [
        "coimbatore street food short",
        "coimbatore food review shorts",
        "coimbatore restaurant review short",
    ],
}

# Max results to fetch per search query
RESULTS_PER_QUERY = 8

# Only include videos shorter than this (in seconds) — keeps only Shorts & brief reviews
MAX_DURATION_SECONDS = 180   # 3 minutes

# ──────────────────────────────────────────────────────

def search_youtube(query: str, max_results: int) -> list:
    """
    Searches YouTube and returns a list of video info dicts.
    Uses yt-dlp's built-in search — no YouTube API key needed!

    The search URL format is:  ytsearchN:QUERY
    where N is the number of results.
    """
    search_url = f"ytsearch{max_results}:{query}"

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,   # Don't download, just get metadata
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(search_url, download=False)
            entries = result.get("entries", [])
            return entries
    except Exception as e:
        print(f"  Search error: {str(e)[:100]}")
        return []


def is_short_form(entry: dict) -> bool:
    """
    Checks if a video qualifies as short-form content.
    YouTube Shorts are <= 60 seconds, but we allow up to MAX_DURATION_SECONDS
    to capture brief food reviews too.
    """
    duration = entry.get("duration", 9999)
    if duration is None:
        return False
    return duration <= MAX_DURATION_SECONDS


def load_config() -> dict:
    if DATASET_CONFIG.exists():
        return json.loads(DATASET_CONFIG.read_text(encoding="utf-8"))
    return {}

def save_config(config: dict):
    DATASET_CONFIG.write_text(
        json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
    )

def get_existing_urls(config: dict) -> set:
    """Returns all URLs already in the config (to avoid duplicates)."""
    urls = set()
    for key, entries in config.items():
        if key.startswith("_"):
            continue
        if isinstance(entries, list):
            for e in entries:
                if isinstance(e, dict):
                    urls.add(e.get("url", ""))
    return urls


def run_finder():
    print("=" * 60)
    print(" FOOD VIDEO FINDER")
    print(" Searching YouTube for real food review Shorts")
    print("=" * 60)

    config = load_config()
    existing_urls = get_existing_urls(config)

    # Preserve the instructions block if it exists
    if "_instructions" not in config:
        config["_instructions"] = {
            "how_to_add_videos": "Add YouTube or Instagram URLs below, or run find_videos.py to auto-discover.",
            "finding_shorts": "On YouTube, search 'city food hidden gem' then filter by Short.",
        }

    total_added = 0

    for city, queries in SEARCH_CONFIG.items():
        print(f"\n[{city.upper()}]")
        if city not in config:
            config[city] = []

        city_added = 0

        for query in queries:
            print(f"  Searching: '{query}' ...", end="", flush=True)
            entries = search_youtube(query, RESULTS_PER_QUERY)

            added_this_query = 0
            for entry in entries:
                video_id  = entry.get("id", "")
                title     = entry.get("title", "No title")
                duration  = entry.get("duration", 0)
                url       = f"https://www.youtube.com/watch?v={video_id}"

                # Skip if already in config
                if url in existing_urls:
                    continue

                # Determine type
                if is_short_form(entry):
                    video_type = "short_form"
                    url = f"https://www.youtube.com/shorts/{video_id}"
                else:
                    video_type = "long_form"

                # Skip long-form for now (focus on shorts)
                if video_type == "long_form":
                    continue

                # Add to config
                safe_title = title.encode("ascii", errors="replace").decode()
                config[city].append({
                    "url": url,
                    "notes": safe_title[:80],
                    "duration_seconds": duration,
                    "type": video_type,
                    "processed": False
                })
                existing_urls.add(url)
                added_this_query += 1

            print(f" found {added_this_query} new shorts")
            city_added += added_this_query

        print(f"  Total new for {city}: {city_added}")
        total_added += city_added

    # Save updated config
    save_config(config)

    print()
    print("=" * 60)
    print(f"  Total new videos found : {total_added}")
    print(f"  Saved to               : {DATASET_CONFIG}")
    print("=" * 60)
    print()

    if total_added > 0:
        print("Next step: run 'python batch_process.py' to process all found videos!")
    else:
        print("No new videos found. The searches may have returned results")
        print("already in your config, or try different search queries.")

    # Show summary of what's in config now
    print()
    print("Current dataset summary:")
    for city in SEARCH_CONFIG.keys():
        entries = config.get(city, [])
        total  = len(entries)
        done   = sum(1 for e in entries if e.get("processed"))
        print(f"  {city:20s} : {total} videos ({done} processed, {total-done} pending)")


if __name__ == "__main__":
    run_finder()
