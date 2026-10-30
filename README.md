# 🍽️ AlgoBite

> **AI-Powered Food Discovery & Context-Aware Navigation Assistant**  
> An intelligent system that transforms your saved YouTube food review playlists into real-time, road-feasible dining recommendations based on your current location, schedule, and preferences.

---

## 💡 The Problem

When you're hungry and away from home, generic apps like Zomato or Google Maps show you hundreds of unfiltered restaurants with zero context on your personal taste, your available time, or whether a place is reachable right now. 

Meanwhile, food lovers already do the research — saving food reviews and vlog recommendations on YouTube — but there's no easy way to query those saved videos by proximity, real road travel time, or opening hours when you're actually out in the city.

---

## 🚀 The Solution

**AlgoBite** bridges this gap:
1. **Ingests** your saved YouTube food playlists and extracts spoken recommendations using speech-to-text.
2. **Structures** unstructured video reviews into restaurant profiles (cuisines, dishes, pricing, operating hours).
3. **Calculates** real road driving times (via OSRM) from where you are standing right now.
4. **Recommends** the single best dining spot using a context-aware AI reasoning engine.

---

## 🏗️ Architecture & Pipeline

```
Your YouTube Food Playlist
        │
        ▼ yt-dlp (audio & metadata extraction)
  Video Audio + Description
        │
        ├── Description ──────────────────────────────────┐
        │   (address, timings, price cues)                │
        ▼                                                  │
  OpenAI Whisper                                          │
  (speech-to-text transcript)                             │
        │                                                  ▼
        └──────────────────► AI Extraction ◄───────┘
                             (structured JSON per restaurant)
                                      │
                                      ▼
                            Restaurant Database
                            (isolated per user account)
                                      │
                     ┌────────────────┼────────────────┐
                     ▼                ▼                ▼
              OSRM Routing     Hours Check      Crowd Estimate
           (road driving time) (open/closed?)   (time-of-day)
                     │                │                │
                     └────────────────┴────────────────┘
                                      │
                                      ▼
                            AI Recommendation Engine
                          (curates the optimal choice)
                                      │
                                      ▼
                          Interactive Web Interface
```

---

## ✨ Features

- 🎬 **Playlist Auto-Sync** — Paste any public YouTube playlist URL; background workers auto-ingest new videos.
- 🎙️ **Multilingual Audio Transcription** — Transcribes video audio across multiple Indian and international languages with Whisper.
- 🤖 **Structured Information Extraction** — Parses restaurant name, locality, must-try dishes, timings, and price range from informal conversational reviews.
- 🗺️ **Real Road Routing (OSRM)** — Uses true road network distances rather than straight-line approximations to ensure spots are reachable within your time budget.
- 🕐 **Operating Hours & Feasibility** — Verifies if kitchens are open at your predicted arrival time.
- 👥 **Crowd & Rush Level Estimation** — Estimates wait times and peak rush hours.
- 🗺️ **Interactive Leaflet Map** — Pinpoints candidate spots with live navigation directions.
- 👤 **Account Isolation** — Secure bcrypt authentication ensuring each user's saved playlists stay private.
- 🌙 **Modern UI** — Clean light/dark mode interface with accessibility support.

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.10+, Flask 3.x |
| **Frontend** | HTML5, Tailwind CSS, Leaflet.js, Phosphor Icons |
| **Speech-to-Text** | OpenAI Whisper |
| **Generative AI** | Google Gemini API (`gemini-2.5-flash`) |
| **Road Routing** | OSRM (Open Source Routing Machine) |
| **Geocoding** | Nominatim / OpenStreetMap |
| **Security** | bcrypt password hashing, Flask session management |

---

## 📁 Project Structure

```
Project_GenAI/
├── .env.example                  ← Environment template for API keys
├── .gitignore                    ← Protects keys, media, and private databases
├── requirements.txt              ← Python project dependencies
│
├── server.py                     ← Flask web server & background daemon
├── batch_process.py              ← Video ingestion & AI parsing pipeline
│
├── src/
│   ├── step2_downloader.py       ← yt-dlp media downloader
│   ├── step3_transcriber.py      ← Whisper transcription engine
│   ├── step4_extractor.py        ← AI structured data extractor
│   ├── step5_suggester.py        ← Context-aware recommendation engine
│   ├── step6_router.py           ← OSRM driving-time calculation & routing
│   ├── step7_crowd.py            ← Crowd estimation & navigation generation
│   ├── step8_hours.py            ← Opening hours verification
│   └── youtube_account_sync.py  ← Playlist synchronization & auth utilities
│
├── templates/
│   ├── index.html                ← Single-page application interface
│   ├── 404.html                  ← Error page
│   └── 500.html                  ← Error page
│
├── data/                         ← Local database & cache storage
└── extension/                    ← Companion Chrome extension
```

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10 or higher
- A free Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey)
- FFmpeg (included in the root repository as `ffmpeg.exe` for Windows)

### Installation

```powershell
# 1. Clone the repository
git clone https://github.com/Lohith-gt/algobite.git
cd algobite

# 2. Set up virtual environment
python -m venv venv
.\venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
copy .env.example .env
# Open .env and insert your GEMINI_API_KEY

# 5. Launch the application
python server.py
```

Visit **`http://localhost:5000`** in your browser.

---

## 🗺️ Roadmap & Future Scope

Plans for upcoming releases:
- [ ] **Instagram Reels & TikTok Ingestion** — Support video links from Instagram and TikTok.
- [ ] **Collaborative Group Playlists** — Allow friends to merge playlists for joint group outings.
- [ ] **Mobile App Interface** — Flutter / React Native frontend for on-the-go queries.
- [ ] **Live Kitchen Status** — Real-time Google Maps Places API fallback for sudden holiday closures.

---

## 👥 Contributors

- **Antharadi Lohith** ([@Lohith-gt](https://github.com/Lohith-gt))
- *Open to contributions! Feel free to open issues or submit pull requests.*

---

## 📜 License

This project is open-source and available under the [MIT License](LICENSE).
