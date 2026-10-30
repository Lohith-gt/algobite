/**
 * Content Script - Food Discovery Assistant v2
 *
 * ONLY runs on: youtube.com/playlist?list=...
 * Does NOT appear on individual video pages.
 *
 * Features:
 *  - Detects the logged-in YouTube account from the page DOM
 *  - Reads ALL video URLs from the current playlist
 *  - Injects a sync toolbar at the top of the playlist page
 *  - Sends the batch of URLs + account info to the local API
 */

(function () {
  "use strict";

  const BACKEND_URL = "http://localhost:8000";
  const INJECT_ID   = "fd-playlist-sync-bar";

  // ── Helpers ────────────────────────────────────────────────

  function getActiveAccount() {
    // Try multiple selectors YouTube uses for the signed-in user name/avatar
    const selectors = [
      "#account-name",
      "ytd-topbar-menu-button-renderer #avatar-btn",
      "#masthead #avatar-btn",
    ];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el) {
        const label = el.getAttribute("aria-label") || el.textContent?.trim();
        if (label && label.length > 1) return label;
      }
    }
    // Fallback: try the channel name in the sidebar
    const channelEl = document.querySelector("yt-formatted-string.ytd-channel-name");
    if (channelEl) return channelEl.textContent?.trim();
    return "unknown_user";
  }

  function getPlaylistMeta() {
    const url   = new URL(window.location.href);
    const listId = url.searchParams.get("list") || "";

    // Playlist title
    const titleEl = document.querySelector(
      "h1.ytd-playlist-header-renderer, yt-formatted-string#title.ytd-playlist-panel-renderer, #title.ytd-playlist-panel-video-renderer"
    );
    const title = titleEl?.textContent?.trim() || listId;

    // Total video count
    const countEl = document.querySelector(
      "yt-formatted-string#stats span, .metadata-stats span"
    );
    const countText = countEl?.textContent?.trim() || "";

    return { listId, title, countText };
  }

  function collectVideoUrls() {
    // YouTube playlist video title links
    const links = document.querySelectorAll(
      "ytd-playlist-video-renderer a#video-title, " +
      "ytd-playlist-panel-video-renderer a#wc-endpoint"
    );
    const urls = [];
    const seen = new Set();
    for (const a of links) {
      const href = a.href || "";
      if (href.includes("/watch?v=") || href.includes("/shorts/")) {
        // Normalise to clean URL without playlist context
        try {
          const u = new URL(href);
          const vid = u.searchParams.get("v");
          const clean = vid
            ? `https://www.youtube.com/watch?v=${vid}`
            : href;
          if (!seen.has(clean)) {
            seen.add(clean);
            urls.push({ url: clean, title: a.textContent?.trim() || "" });
          }
        } catch (_) {
          if (!seen.has(href)) {
            seen.add(href);
            urls.push({ url: href, title: a.textContent?.trim() || "" });
          }
        }
      }
    }
    return urls;
  }

  // ── Sync Bar UI ────────────────────────────────────────────

  function injectSyncBar() {
    if (document.getElementById(INJECT_ID)) return;

    const meta    = getPlaylistMeta();
    const account = getActiveAccount();

    const bar = document.createElement("div");
    bar.id    = INJECT_ID;
    bar.innerHTML = `
      <div class="fd-bar-inner">
        <div class="fd-bar-left">
          <span class="fd-logo">🍽️</span>
          <div class="fd-bar-info">
            <span class="fd-bar-title">Food Discovery AI</span>
            <span class="fd-bar-sub">
              Playlist: <strong>${escapeHtml(meta.title)}</strong>
              &nbsp;·&nbsp;
              Account: <strong>${escapeHtml(account)}</strong>
            </span>
          </div>
        </div>
        <div class="fd-bar-right">
          <span id="fd-video-count" class="fd-count">Detecting videos...</span>
          <button id="fd-sync-btn" class="fd-sync-btn">
            🚀 Sync All Food Videos
          </button>
          <button id="fd-bar-close" class="fd-close-btn" title="Dismiss">✕</button>
        </div>
      </div>
      <div id="fd-bar-status" class="fd-bar-status fd-hidden"></div>
    `;

    // Insert at the very top of the page (after header)
    const header = document.querySelector("ytd-masthead") || document.body.firstChild;
    if (header && header.parentNode) {
      header.parentNode.insertBefore(bar, header.nextSibling);
    } else {
      document.body.insertBefore(bar, document.body.firstChild);
    }

    // Count videos once DOM settles
    setTimeout(() => {
      const videos = collectVideoUrls();
      const countEl = document.getElementById("fd-video-count");
      if (countEl) countEl.textContent = `${videos.length} video(s) found`;
    }, 1500);

    // Sync button
    document.getElementById("fd-sync-btn").addEventListener("click", () => {
      handleSyncAll(account, meta);
    });

    // Close button
    document.getElementById("fd-bar-close").addEventListener("click", () => {
      bar.remove();
    });
  }

  async function handleSyncAll(account, meta) {
    const btn = document.getElementById("fd-sync-btn");
    const statusEl = document.getElementById("fd-bar-status");

    btn.disabled = true;
    btn.textContent = "⏳ Collecting videos...";
    showStatus("Scanning playlist for food review videos...", "info");

    // Allow DOM to update
    await sleep(300);

    // Scroll to load all lazy-loaded videos (YouTube lazy-renders)
    await scrollToLoadAll();

    const videos = collectVideoUrls();
    if (videos.length === 0) {
      showStatus("No videos found in this playlist. Try scrolling down first.", "error");
      btn.disabled = false;
      btn.textContent = "🚀 Sync All Food Videos";
      return;
    }

    showStatus(`Found ${videos.length} videos. Sending to AI pipeline...`, "info");
    btn.textContent = `⏳ Queuing ${videos.length} videos...`;

    try {
      const response = await fetch(`${BACKEND_URL}/api/batch_ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          videos: videos,
          user_id: sanitizeId(account),
          user_name: account,
          playlist_id: meta.listId,
          playlist_name: meta.title,
        }),
      });

      const data = await response.json();
      if (response.ok) {
        const newCount   = data.queued || 0;
        const skipCount  = data.skipped || 0;
        showStatus(
          `✅ ${newCount} new video(s) queued for AI transcription! ${skipCount} already in database. Check extension popup for progress.`,
          "success"
        );
        btn.textContent = `✅ Queued ${newCount} videos`;
      } else {
        showStatus(`❌ ${data.detail || "Batch ingest failed"}`, "error");
        btn.disabled = false;
        btn.textContent = "🚀 Retry Sync";
      }
    } catch (err) {
      showStatus("❌ Backend offline! Please run api_server.py first.", "error");
      btn.disabled = false;
      btn.textContent = "🚀 Retry Sync";
    }
  }

  async function scrollToLoadAll() {
    // Scroll to bottom multiple times to trigger YouTube's lazy-loading
    const delay = 600;
    for (let i = 0; i < 5; i++) {
      window.scrollTo(0, document.body.scrollHeight);
      await sleep(delay);
    }
    window.scrollTo(0, 0);
    await sleep(300);
  }

  function showStatus(msg, type) {
    const el = document.getElementById("fd-bar-status");
    if (!el) return;
    el.textContent = msg;
    el.className = `fd-bar-status fd-${type}`;
  }

  function sanitizeId(str) {
    return (str || "unknown").toLowerCase().replace(/[^a-z0-9_]/g, "_").slice(0, 40);
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  // ── Init: only on playlist pages ──────────────────────────

  function init() {
    const url = window.location.href;
    if (!url.includes("youtube.com/playlist")) return;

    // Wait briefly for page content to load
    setTimeout(injectSyncBar, 2000);
  }

  // Handle YouTube SPA navigation (History API)
  let _lastUrl = location.href;
  const _observer = new MutationObserver(() => {
    const currentUrl = location.href;
    if (currentUrl !== _lastUrl) {
      _lastUrl = currentUrl;
      if (currentUrl.includes("youtube.com/playlist")) {
        setTimeout(injectSyncBar, 2000);
      }
    }
  });
  _observer.observe(document.body, { childList: true, subtree: true });

  init();
})();
