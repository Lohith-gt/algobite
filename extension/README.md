# 🍽️ Food Discovery Assistant - Browser Extension (Phase 4)

Save food review videos directly from **YouTube** (Shorts & regular videos) and **Instagram** (Reels & posts) into your AI restaurant database with **1 click**.

---

## 🚀 How to Install in Your Browser

Works on **Google Chrome**, **Microsoft Edge**, **Brave**, **Opera**, or any Chromium browser.

### Step 1: Open Extension Management
- **Google Chrome**: Go to `chrome://extensions/`
- **Microsoft Edge**: Go to `edge://extensions/`
- **Brave**: Go to `brave://extensions/`

### Step 2: Enable Developer Mode
- Toggle on the **"Developer mode"** switch in the top-right corner.

### Step 3: Load the Extension
1. Click the **"Load unpacked"** button in the top-left.
2. Navigate to your project folder:
   ```
   D:\Lohith\college\sem7\Generative AI\Project_GenAI\extension
   ```
3. Click **"Select Folder"**.

🎉 **Done!** The extension icon will now appear in your browser's toolbar. Pin it for quick access!

---

## 🎯 How to Use

### Method A: The In-Page Floating Button
1. Open any **YouTube Short** (`youtube.com/shorts/...`) or **Instagram Reel** (`instagram.com/reel/...`).
2. You'll see a floating **"🍽️ Save to Food Discovery"** button in the bottom-right corner.
3. Click it! You'll get an instant notification:
   > `✅ Queued! Audio downloading & Whisper transcribing...`

### Method B: The Extension Popup
1. While watching any food video, click the **Food Discovery icon** in your toolbar.
2. The popup automatically detects the current video.
3. Click **"🚀 Save This Video to Database"**.
4. You can also view recent ingestion tasks and their live AI extraction progress.

### Method C: Manual Paste in Popup
1. Click the extension icon anytime.
2. Paste any YouTube or Instagram link into the input box and click **"Add"**.

---

## ⚙️ Backend Status

The extension communicates with the local FastAPI ingestion server at:
```
http://localhost:8000
```

To run the backend server:
```powershell
.\venv\Scripts\python.exe api_server.py
```

The extension popup shows a live connection badge:
- 🟢 **Online** — Ready to ingest videos
- 🔴 **Offline** — Start `api_server.py` in your terminal
