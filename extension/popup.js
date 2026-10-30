const BACKEND_URL = "http://localhost:8000";

let currentUserId   = null;
let currentUserName = null;

document.addEventListener("DOMContentLoaded", async () => {
  await checkBackendHealth();
  await detectYouTubeAccount();
  await loadStats();
  loadTasks();

  document.getElementById("refresh-tasks-btn").addEventListener("click", loadTasks);
  document.getElementById("open-watch-later-btn").addEventListener("click", () => {
    chrome.tabs.create({ url: "https://www.youtube.com/playlist?list=WL" });
  });

  // Refresh tasks every 3s
  setInterval(loadTasks, 3000);
  // Refresh stats every 10s
  setInterval(loadStats, 10000);
});

// ── Backend Health ─────────────────────────────────────────

async function checkBackendHealth() {
  const badge = document.getElementById("backend-status");
  const text  = document.getElementById("status-text");

  try {
    const res  = await fetch(`${BACKEND_URL}/api/health`, { method: "GET" });
    const data = await res.json();
    badge.className = "status-badge online";
    text.textContent = `Online (${data.total_restaurants} places)`;
  } catch {
    badge.className  = "status-badge offline";
    text.textContent = "Offline — run api_server.py";
  }
}

// ── Detect active YouTube account by injecting into tab ───

async function detectYouTubeAccount() {
  const nameEl   = document.getElementById("account-name-display");
  const idEl     = document.getElementById("account-id-display");
  const badgeEl  = document.getElementById("account-badge");

  try {
    // Query the current active tab
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    if (!tab || !tab.url?.includes("youtube.com")) {
      // If not on YouTube, try to find any open YouTube tab
      const ytTabs = await chrome.tabs.query({ url: "https://www.youtube.com/*" });
      if (ytTabs.length === 0) {
        nameEl.textContent  = "Not on YouTube";
        idEl.textContent    = "Open YouTube to detect account";
        badgeEl.textContent = "—";
        return;
      }
      // Use first YouTube tab
      await readAccountFromTab(ytTabs[0].id, nameEl, idEl, badgeEl);
    } else {
      await readAccountFromTab(tab.id, nameEl, idEl, badgeEl);
    }
  } catch (err) {
    nameEl.textContent  = "Detection failed";
    idEl.textContent    = err.message?.slice(0, 60) || "Unknown error";
  }
}

async function readAccountFromTab(tabId, nameEl, idEl, badgeEl) {
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        // Try multiple selectors YouTube uses for the signed-in user
        const selectors = [
          { sel: "#account-name", attr: "textContent" },
          { sel: "#avatar-btn",   attr: "aria-label"  },
        ];
        for (const { sel, attr } of selectors) {
          const el  = document.querySelector(sel);
          if (!el) continue;
          const val = attr === "textContent" ? el.textContent?.trim() : el.getAttribute(attr);
          if (val && val.length > 0) return val;
        }
        // Last resort: look at page title or channel meta
        const channelEl = document.querySelector("yt-formatted-string#text.ytd-channel-name");
        if (channelEl) return channelEl.textContent?.trim();
        return null;
      },
    });

    const rawName = results?.[0]?.result;

    if (rawName) {
      currentUserName = rawName;
      currentUserId   = sanitizeId(rawName);
      nameEl.textContent  = rawName;
      idEl.textContent    = `user ID: ${currentUserId}`;
      badgeEl.textContent = "✅ Detected";
      badgeEl.style.color = "#2EC4B6";

      // Store in extension storage so content script can use it
      chrome.storage.local.set({ user_id: currentUserId, user_name: currentUserName });
    } else {
      nameEl.textContent  = "Sign into YouTube to detect account";
      idEl.textContent    = "";
      badgeEl.textContent = "⚠️";
    }
  } catch (err) {
    nameEl.textContent  = "Cannot detect (page restricted)";
    idEl.textContent    = "";
    badgeEl.textContent = "—";
  }
}

function sanitizeId(str) {
  return (str || "unknown").toLowerCase().replace(/[^a-z0-9_]/g, "_").slice(0, 40);
}

// ── Stats ──────────────────────────────────────────────────

async function loadStats() {
  try {
    const url = currentUserId
      ? `${BACKEND_URL}/api/stats?user_id=${encodeURIComponent(currentUserId)}`
      : `${BACKEND_URL}/api/stats`;
    const res  = await fetch(url);
    const data = await res.json();

    document.getElementById("stat-my-restaurants").textContent =
      data.user_restaurant_count ?? "—";
    document.getElementById("stat-total").textContent =
      data.total_restaurants ?? "—";
    document.getElementById("stat-cities").textContent =
      Object.keys(data.cities || {}).length || "—";
  } catch {
    // Silently ignore offline
  }
}

// ── Tasks ──────────────────────────────────────────────────

async function loadTasks() {
  const listEl = document.getElementById("tasks-list");
  try {
    const url = currentUserId
      ? `${BACKEND_URL}/api/tasks?user_id=${encodeURIComponent(currentUserId)}`
      : `${BACKEND_URL}/api/tasks`;
    const res   = await fetch(url);
    if (!res.ok) return;
    const tasks = await res.json();

    if (!tasks || tasks.length === 0) {
      listEl.innerHTML = '<div class="empty-state">No active ingestion tasks</div>';
      return;
    }

    listEl.innerHTML = tasks.map(t => {
      const urlShort  = (t.title || t.url || "").replace(/^https?:\/\/(www\.)?youtube\.com\//, "");
      const statusCls = t.status || "queued";
      const label     = formatStatus(t.status);
      const step      = t.step || "In queue";
      let extra = "";
      if (t.extracted_restaurants?.length) {
        extra = ` · Found: ${t.extracted_restaurants.join(", ")}`;
      }
      return `
        <div class="task-item">
          <div class="task-info">
            <div class="task-url" title="${t.url}">${escapeHtml(urlShort)}</div>
            <div class="task-step">${escapeHtml(step)}${extra}</div>
          </div>
          <span class="task-status ${statusCls}">${label}</span>
        </div>
      `;
    }).join("");
  } catch {
    // Silently ignore offline polling
  }
}

function formatStatus(s) {
  return { queued: "Queued", processing: "Running", completed: "Done",
           completed_empty: "No place", failed: "Failed", duplicate: "Exists" }[s] || s;
}

function showToast(message, type = "info") {
  const toast = document.getElementById("toast-message");
  toast.textContent = message;
  toast.className   = `toast ${type}`;
  setTimeout(() => { toast.className = "toast hidden"; }, 4000);
}

function escapeHtml(text) {
  const d = document.createElement("div");
  d.textContent = text;
  return d.innerHTML;
}
