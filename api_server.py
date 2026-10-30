"""
API Server for Food Discovery Extension (Phase 4)
=================================================
FastAPI backend service running on http://localhost:8000
Receives video URLs from the Chrome/Edge browser extension,
processes them in the background using the AI pipeline (yt-dlp + Whisper + Gemini),
and persists the extracted restaurants into data/restaurants.json.

Endpoints:
  - GET  /api/health            Healthcheck & backend status
  - POST /api/ingest            Queue a YouTube / Instagram URL for ingestion
  - GET  /api/tasks             List recent ingestion tasks & statuses
  - GET  /api/tasks/{task_id}   Get status of a specific task
  - GET  /api/stats             Database counts & city stats
"""

import os
import sys

# Configure UTF-8 encoding for Windows console to prevent cp1252 charmap crashes
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import uuid
import time
import json
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List

import uvicorn
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl

# Add project root and src/ to sys.path
BASE_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "src"))

# Import pipeline functions
from batch_process import (
    process_single_url,
    load_restaurants,
    load_config,
    save_config,
    normalize_city,
)

# Initialize FastAPI
app = FastAPI(
    title="Food Discovery Assistant - Ingestion API",
    description="Backend API for 1-click video ingestion from YouTube and Instagram",
    version="1.0.0"
)

# Enable CORS for Chrome/Edge extensions and local clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows browser extension origins (chrome-extension://...)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory task tracker
tasks_lock = threading.Lock()
tasks: Dict[str, Dict[str, Any]] = {}
task_queue: List[str] = []
is_worker_running = False


class IngestRequest(BaseModel):
    url: str
    city: Optional[str] = "auto"
    video_type: Optional[str] = "auto"
    source_title: Optional[str] = None
    source_description: Optional[str] = None  # Video description for richer extraction
    user_id: Optional[str] = None        # YouTube account id (sanitised channel name)
    user_name: Optional[str] = None      # Human-readable account name


class VideoItem(BaseModel):
    url: str
    title: Optional[str] = None
    description: Optional[str] = None    # Video description — key for restaurant name/address accuracy


class BatchIngestRequest(BaseModel):
    videos: List[VideoItem]              # All videos from the playlist
    user_id: str                         # Sanitised YouTube account ID
    user_name: Optional[str] = None     # Display name
    playlist_id: Optional[str] = None   # YouTube playlist ID
    playlist_name: Optional[str] = None # Human-readable playlist name


class IngestResponse(BaseModel):
    task_id: str
    status: str
    message: str
    url: str


def background_worker():
    """Sequential background worker that processes queued videos."""
    global is_worker_running
    while True:
        task_id = None
        with tasks_lock:
            if task_queue:
                task_id = task_queue.pop(0)
            else:
                is_worker_running = False
                break

        if not task_id:
            break

        with tasks_lock:
            task = tasks.get(task_id)
            if not task:
                continue
            task["status"] = "processing"
            task["step"] = "Downloading audio & metadata..."
            task["started_at"] = time.time()
            # Snapshot fields needed for processing (read while holding the lock)
            url   = task["url"]
            city  = task.get("city") or "auto"
            vtype = task.get("video_type") or "auto"
            uid   = task.get("user_id") or None
            uname = task.get("user_name") or None
            hint_desc = task.get("description") or ""   # Pre-known description (from playlist metadata)

        def progress_callback(msg: str):
            with tasks_lock:
                if task_id in tasks:
                    tasks[task_id]["step"] = msg

        try:
            extracted, msg = process_single_url(
                url=url,
                city=city,
                video_type=vtype,
                progress_cb=progress_callback,
                user_id=uid,
                user_name=uname,
                hint_description=hint_desc,
            )

            with tasks_lock:
                task["completed_at"] = time.time()
                if extracted:
                    task["status"] = "completed"
                    task["step"] = "Completed successfully!"
                    task["extracted_count"] = len(extracted)
                    task["extracted_restaurants"] = [
                        r.get("restaurant_name", "Unknown") for r in extracted
                    ]
                    task["message"] = msg
                else:
                    task["status"] = "completed_empty"
                    task["step"] = "No restaurant identified"
                    task["extracted_count"] = 0
                    task["extracted_restaurants"] = []
                    task["message"] = msg
        except Exception as e:
            with tasks_lock:
                task["status"] = "failed"
                task["step"] = "Error encountered"
                task["error"] = str(e)
                task["completed_at"] = time.time()


@app.get("/api/health")
def health():
    """Health check endpoint to verify backend connectivity."""
    db = load_restaurants()
    return {
        "status": "online",
        "service": "Food Discovery Ingestion API",
        "version": "1.0.0",
        "total_restaurants": len(db),
        "queued_tasks": len(task_queue),
        "active_tasks": sum(1 for t in tasks.values() if t.get("status") == "processing")
    }


@app.get("/api/stats")
def stats(user_id: Optional[str] = None):
    """Returns database summary statistics, optionally filtered by user_id."""
    db = load_restaurants()
    city_counts: Dict[str, int] = {}
    for r in db:
        c = normalize_city(r.get("city", "Unknown"))
        city_counts[c] = city_counts.get(c, 0) + 1

    # Count user's own restaurants if user_id provided
    user_count = 0
    if user_id:
        user_count = sum(1 for r in db if r.get("source_user_id") == user_id)

    return {
        "total_restaurants": len(db),
        "user_restaurant_count": user_count if user_id else len(db),
        "cities": city_counts,
        "recent_restaurants": [
            {
                "name": r.get("restaurant_name"),
                "city": r.get("city"),
                "area": r.get("area_or_locality"),
                "cuisine": r.get("cuisine_type"),
                "source_user": r.get("source_user_name", "—"),
            }
            for r in db[-5:]
        ]
    }


@app.post("/api/ingest", response_model=IngestResponse)
def ingest_video(payload: IngestRequest):
    """
    Ingests a video URL from YouTube or Instagram.
    Immediately queues the task and returns a task_id for tracking.
    """
    global is_worker_running
    url = payload.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL cannot be empty")

    # Basic URL validation
    valid_domains = ["youtube.com", "youtu.be", "instagram.com"]
    if not any(d in url.lower() for d in valid_domains):
        raise HTTPException(
            status_code=400,
            detail="Unsupported platform. Please provide a YouTube or Instagram video link."
        )

    # Check if already processed
    db = load_restaurants()
    for r in db:
        if r.get("source_url") == url:
            return IngestResponse(
                task_id="already_exists",
                status="duplicate",
                message=f"Restaurant '{r.get('restaurant_name')}' from this URL is already in database!",
                url=url
            )

    task_id = str(uuid.uuid4())[:8]
    with tasks_lock:
        tasks[task_id] = {
            "task_id": task_id,
            "url": url,
            "city": payload.city,
            "video_type": payload.video_type,
            "title": payload.source_title,
            "description": payload.source_description or "",   # Forward description to Gemini
            "status": "queued",
            "step": "Waiting in queue...",
            "created_at": time.time(),
            "user_id": payload.user_id,
            "user_name": payload.user_name,
            "extracted_count": 0,
            "extracted_restaurants": []
        }
        task_queue.append(task_id)

        if not is_worker_running:
            is_worker_running = True
            threading.Thread(target=background_worker, daemon=True).start()

    return IngestResponse(
        task_id=task_id,
        status="queued",
        message="Video queued for AI transcription & extraction!",
        url=url
    )


@app.post("/api/batch_ingest")
def batch_ingest(payload: BatchIngestRequest):
    """
    Batch ingest all videos from a YouTube playlist.
    Called by the extension when the user clicks "Sync All Food Videos"
    on a YouTube playlist page. Each video is queued as a separate task.
    Skips URLs already in the database.
    """
    global is_worker_running

    db = load_restaurants()
    already_processed = {r.get("source_url", "") for r in db}

    queued   = 0
    skipped  = 0
    task_ids = []

    for item in payload.videos:
        url = item.url.strip()
        if not url:
            continue
        if url in already_processed:
            skipped += 1
            continue

        task_id = str(uuid.uuid4())[:8]
        with tasks_lock:
            tasks[task_id] = {
                "task_id":    task_id,
                "url":        url,
                "title":      item.title or url,
                "description": item.description or "",  # Video description — improves Gemini accuracy
                "city":       "auto",
                "video_type": "auto",
                "user_id":    payload.user_id,
                "user_name":  payload.user_name,
                "playlist_id":   payload.playlist_id,
                "playlist_name": payload.playlist_name,
                "status":     "queued",
                "step":       "Waiting in queue...",
                "created_at": time.time(),
                "extracted_count": 0,
                "extracted_restaurants": [],
            }
            task_queue.append(task_id)
            task_ids.append(task_id)
            queued += 1

    with tasks_lock:
        if not is_worker_running and task_ids:
            is_worker_running = True
            threading.Thread(target=background_worker, daemon=True).start()

    return {
        "queued":   queued,
        "skipped":  skipped,
        "task_ids": task_ids,
        "message":  f"Queued {queued} new video(s) from playlist '{payload.playlist_name or payload.playlist_id}'. {skipped} already in database.",
        "user_id":  payload.user_id,
    }


@app.get("/api/tasks")
def list_tasks(user_id: Optional[str] = None):
    """Lists recent tasks. If user_id is provided, returns only that user's tasks."""
    with tasks_lock:
        all_tasks = tasks.values()
        if user_id:
            all_tasks = [t for t in all_tasks if t.get("user_id") == user_id]
        sorted_tasks = sorted(all_tasks, key=lambda t: t.get("created_at", 0), reverse=True)
        return sorted_tasks[:20]


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    """Returns details for a single task."""
    with tasks_lock:
        task = tasks.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task


if __name__ == "__main__":
    print("=" * 60)
    print(" [API] FOOD DISCOVERY - INGESTION API SERVER")
    print(" [API] Running at http://localhost:8000")
    print(" [API] Docs at    http://localhost:8000/docs")
    print("=" * 60)

    try:
        from youtube_account_sync import start_auto_sync_daemon
        start_auto_sync_daemon(interval_seconds=60)
    except Exception as e:
        print(f"[API SERVER] Auto-sync daemon warning: {e}")

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
