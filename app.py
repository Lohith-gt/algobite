"""
Food Discovery Assistant — Streamlit Web Application
=====================================================
Interactive web dashboard for the AI Food Discovery System.

Run with:
    streamlit run app.py

Tabs:
  1. Search      — Query by city, location, time, preferences → AI recommendation + map
  2. Add         — Paste YouTube URL → auto-ingest into the database
  3. Database    — Browse all restaurants currently in the database
"""

import streamlit as st
import streamlit.components.v1 as components
import sys
import os
import json
import time
import subprocess
from pathlib import Path

# ── Path Setup ────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
SRC_DIR = BASE_DIR / "src"
DATA_DIR = BASE_DIR / "data"
RESTAURANTS_DB = DATA_DIR / "restaurants.json"
DATASET_CONFIG = DATA_DIR / "dataset_urls.json"

sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(SRC_DIR))

os.environ["PYTHONIOENCODING"] = "utf-8"

# ── Page Configuration ────────────────────────────────────
st.set_page_config(
    page_title="Food Discovery Assistant",
    page_icon=":material/restaurant:",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Google Fonts (Meridian Design System) ────────────────────
st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;0,600;0,700;1,500&family=JetBrains+Mono:wght@400;500;600&family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
""", unsafe_allow_html=True)

# ── Theme JS Bridge + Design System CSS ─────────────────────────

# JS bridge: runs in a same-origin iframe, reads Streamlit's chosen theme from
# localStorage and writes data-app-theme="dark"|"light" on the parent <html>.
# Our CSS then uses [data-app-theme="dark"] selectors for the custom dark look.
components.html("""
<script>
(function() {
    function applyTheme() {
        try {
            var raw = parent.localStorage.getItem('stActiveTheme');
            var isDark = false;
            if (raw) {
                var t = JSON.parse(raw);
                isDark = (t.base === 'dark' || t.name === 'Dark');
            } else {
                // Fallback: detect via the --background-color CSS variable
                var bg = parent.getComputedStyle(parent.document.documentElement)
                               .getPropertyValue('--background-color').trim();
                isDark = (bg === '#0e1117');
            }
            parent.document.documentElement.setAttribute(
                'data-app-theme', isDark ? 'dark' : 'light'
            );
            var dep = parent.document.querySelectorAll('[data-testid="stAppDeployButton"], .stAppDeployButton');
            dep.forEach(function(el) { el.style.display = 'none'; });

            // Consistent placeholder for Current time
            var timeInputs = parent.document.querySelectorAll('input[placeholder="HH:mm"]');
            timeInputs.forEach(function(inp) { inp.placeholder = 'e.g. 14:30'; });

            // Sync dynamic slider value next to label while dragging
            var sliders = parent.document.querySelectorAll('[data-testid="stSlider"]');
            sliders.forEach(function(s) {
                var thumb = s.querySelector('[role="slider"]');
                var labelP = s.querySelector('[data-testid="stWidgetLabel"] label p');
                if (thumb && labelP) {
                    var val = thumb.getAttribute('aria-valuenow');
                    if (val) {
                        if (labelP.textContent.indexOf('Available time') !== -1) {
                            var num = parseFloat(val);
                            labelP.textContent = 'Available time (hours): ' + (isNaN(num) ? val : num.toFixed(2));
                        } else if (labelP.textContent.indexOf('Dining time') !== -1) {
                            labelP.textContent = 'Dining time to reserve (minutes): ' + val;
                        }
                    }
                }
            });
        } catch(e) {}
    }
    applyTheme();
    setInterval(applyTheme, 400);
    try { parent.window.addEventListener('storage', applyTheme); } catch(e) {}
})();
</script>
""", height=0, scrolling=False)

# Hide the 0-height component wrapper gap
st.markdown("""
<style>
    /* ── Hide the JS-bridge component wrapper ── */
    iframe[height="0"] { display: none !important; }
    [data-testid="stCustomComponentV1"]:has(iframe[height="0"]) {
        display: none !important;
    }

    /* ── Hide Deploy button completely ── */
    [data-testid="stAppDeployButton"],
    .stAppDeployButton,
    [data-testid="stDeployButton"],
    .stDeployButton,
    [data-testid="stToolbarActions"] .stAppDeployButton,
    [data-testid="stHeader"] .stAppDeployButton,
    header .stAppDeployButton,
    header [data-testid="stAppDeployButton"] {
        display: none !important;
        visibility: hidden !important;
        opacity: 0 !important;
        width: 0 !important;
        height: 0 !important;
        pointer-events: none !important;
    }

    /* ── Global layout ── */
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
        max-width: 1200px;
    }

    /* ── Global font ── */
    body, .stApp, [data-testid="stAppViewContainer"],
    [data-testid="stSidebar"], .stMarkdown, p, span, label, div {
        font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
    }

    /* ================================================================
       LIGHT MODE — Meridian Design System
       Palette: #F7F4EF alabaster, #EFEAE1 sand, #121917 obsidian, #5A6560 muted
       Accent:  #C86D51 terracotta, #1D4ED8 cobalt-blue (buttons/tabs/sliders)
       ================================================================ */

    /* ── Page Header ── */
    .app-header {
        border-bottom: 1px solid rgba(18,25,23,0.1);
        padding-bottom: 1rem;
        margin-bottom: 1.5rem;
    }
    .app-header h1 {
        font-family: 'Cormorant Garamond', Georgia, serif !important;
        font-size: 2rem;
        font-weight: 700;
        margin: 0 0 0.25rem 0;
        letter-spacing: -0.02em;
        color: #121917;
    }
    .app-header p {
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        font-size: 0.95rem;
        margin: 0;
        color: #5A6560;
    }

    /* ── Auth screen ── */
    .auth-header {
        background: #EFEAE1;
        border: 1px solid rgba(18,25,23,0.12);
        border-radius: 20px;
        padding: 1.25rem 1.5rem;
        margin-bottom: 1.25rem;
    }
    .auth-header h2 {
        font-family: 'Cormorant Garamond', Georgia, serif !important;
        font-size: 1.3rem;
        font-weight: 600;
        margin: 0 0 0.4rem 0;
        color: #121917;
    }
    .auth-header p {
        font-size: 0.88rem;
        margin: 0;
        line-height: 1.5;
        color: #5A6560;
    }

    /* ── Sidebar profile card ── */
    .profile-card {
        background: #F7F4EF !important;
        border: 1px solid rgba(18,25,23,0.1);
        border-radius: 20px;
        padding: 1rem;
        margin-bottom: 0.8rem;
        text-align: center;
        transition: border-color 0.3s ease;
    }
    .profile-card:hover { border-color: #C86D51; }
    .profile-avatar {
        width: 48px; height: 48px;
        border-radius: 50%;
        background: #121917 !important;
        color: #F7F4EF !important;
        font-size: 1.2rem; font-weight: 700;
        display: flex; align-items: center; justify-content: center;
        margin: 0 auto 0.6rem auto;
        line-height: 48px; text-align: center;
    }
    .profile-name {
        font-family: 'Cormorant Garamond', Georgia, serif !important;
        font-size: 1.1rem;
        font-weight: 600;
        margin-bottom: 0.15rem;
        color: #121917;
    }
    .profile-username {
        font-family: 'JetBrains Mono', 'Fira Code', monospace !important;
        font-size: 0.72rem;
        color: #5A6560;
    }

    /* ── Status pills ── */
    .status-pill {
        display: inline-block;
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 0.68rem; font-weight: 600;
        padding: 0.2rem 0.7rem; border-radius: 9999px; margin: 0.15rem 0;
        letter-spacing: 0.08em;
    }
    .pill-private { background: rgba(200,109,81,0.12); color: #7A3520; border: 1px solid rgba(200,109,81,0.3); }
    .pill-guest   { background: rgba(18,25,23,0.06);   color: #5A6560; border: 1px solid rgba(18,25,23,0.12); }
    .pill-sync    { background: rgba(52,211,153,0.12); color: #065F46; border: 1px solid rgba(52,211,153,0.3); }

    /* ── Saved Places & Metric (scaled down to balance sidebar hierarchy) ── */
    [data-testid="stMetricLabel"],
    [data-testid="stMetricLabel"] p,
    [data-testid="stMetricLabel"] span { font-size: 0.88rem !important; font-weight: 600 !important; }
    [data-testid="stMetricValue"],
    [data-testid="stMetricValue"] div  { font-size: 1.45rem !important; font-weight: 700 !important; }

    /* ── City row ── */
    .city-row {
        display: flex; justify-content: space-between; align-items: center;
        padding: 0.35rem 0; font-size: 0.88rem;
        border-bottom: 1px solid rgba(18,25,23,0.08);
        font-family: 'Plus Jakarta Sans', sans-serif !important;
    }
    .city-row:last-child { border-bottom: none; }
    .city-count {
        font-family: 'JetBrains Mono', monospace !important;
        font-weight: 700;
        color: #C86D51;
    }

    /* ── Cards in main area ── */
    .result-card, .db-card, .sync-card {
        background: #F7F4EF;
        border: 1px solid rgba(18,25,23,0.1);
        border-radius: 20px;
        padding: 1.25rem 1.5rem;
        margin: 0.6rem 0;
        transition: transform 0.4s ease, box-shadow 0.4s ease, border-color 0.3s ease;
    }
    .result-card:hover, .db-card:hover, .sync-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 8px 30px rgba(18,25,23,0.08);
        border-color: #C86D51;
    }
    .result-card-name, .db-card-name, .sync-card-title {
        font-family: 'Cormorant Garamond', Georgia, serif !important;
        font-size: 1.15rem; font-weight: 600;
        margin: 0 0 0.2rem 0;
        color: #121917;
    }
    .result-card-sub, .db-card-location, .sync-card-meta {
        font-size: 0.85rem;
        margin: 0 0 0.6rem 0;
        color: #5A6560;
    }

    /* ── AI recommendation card ── */
    .ai-card {
        background: #F7F4EF;
        border: 1px solid rgba(18,25,23,0.1);
        border-left: 4px solid #C86D51;
        border-radius: 20px;
        padding: 1.2rem 1.5rem;
        margin: 0.8rem 0;
        line-height: 1.7;
        color: #121917;
    }

    /* ── Badges ── */
    .badge {
        display: inline-block;
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 0.68rem; font-weight: 600;
        padding: 0.15rem 0.55rem; border-radius: 6px;
        margin-left: 0.4rem; vertical-align: middle;
    }
    .badge-verified { background: #DCFCE7; color: #15803D; border: 1px solid #BBF7D0; }
    .badge-positive { background: #DCFCE7; color: #15803D; border: 1px solid #BBF7D0; }
    .badge-mixed    { background: #FEF9C3; color: #A16207; border: 1px solid #FDE68A; }
    .badge-negative { background: #FEE2E2; color: #B91C1C; border: 1px solid #FECACA; }

    /* ── Metadata & Dish list ── */
    .meta-grid {
        display: grid; grid-template-columns: 1fr 1fr;
        gap: 0.3rem 1.2rem; font-size: 0.84rem; margin: 0.5rem 0;
    }
    .meta-value { font-weight: 500; color: #121917; }
    .dish-item  { font-size: 0.84rem; padding: 0.1rem 0; color: #121917; }

    /* ── Section divider ── */
    .section-rule { border: none; border-top: 1px solid rgba(18,25,23,0.1); margin: 0.6rem 0; }

    /* ── Quick links ── */
    .quick-link {
        display: inline-block; font-size: 0.82rem; font-weight: 500;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        color: #C86D51; text-decoration: none;
        padding: 0.25rem 0.75rem;
        border: 1px solid rgba(200,109,81,0.25); border-radius: 9999px;
        margin-right: 0.5rem; margin-top: 0.4rem;
        transition: background 0.2s ease;
    }
    .quick-link:hover { background: rgba(200,109,81,0.08); }

    /* ── Info note strip ── */
    .info-strip {
        background: rgba(200,109,81,0.06) !important;
        border: 1px solid rgba(200,109,81,0.2);
        border-left: 3px solid #C86D51;
        border-radius: 12px; padding: 0.55rem 0.9rem;
        font-size: 0.84rem; margin-bottom: 0.8rem;
        color: #7A3520 !important;
    }

    /* ── Section heading ── */
    .section-heading {
        font-family: 'Cormorant Garamond', Georgia, serif !important;
        font-size: 1.15rem; font-weight: 600;
        margin: 1.2rem 0 0.6rem 0; padding-bottom: 0.3rem;
        border-bottom: 1px solid rgba(18,25,23,0.12);
        color: #121917;
    }

    /* ── Sidebar footer ── */
    .sidebar-footer {
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 0.68rem; text-align: center; padding: 0.5rem 0; line-height: 1.6;
        color: #5A6560;
    }

    /* ── Hide heading anchor link icons ── */
    .stMarkdown h1 a, .stMarkdown h2 a, .stMarkdown h3 a,
    h1 a[href^="#"], h2 a[href^="#"], h3 a[href^="#"],
    [data-testid="stMarkdown"] a.anchor-link,
    a.anchor-link { display: none !important; }

    /* ── Expander ── */
    [data-testid="stExpander"] { border: 1px solid rgba(18,25,23,0.1) !important; border-radius: 16px !important; }

    /* ── Tighter Visual Grouping: labels & input fields ── */
    [data-testid="stWidgetLabel"] {
        margin-bottom: -0.35rem !important;
        padding-bottom: 0 !important;
    }
    [data-testid="stWidgetLabel"] label,
    [data-testid="stWidgetLabel"] p {
        margin-bottom: 0.1rem !important;
    }
    [data-testid="stSlider"] > div:first-child {
        margin-bottom: -0.35rem !important;
    }

    /* ── Slider Values: hide floating middle value to keep focus on label ── */
    [data-testid="stSliderThumbValue"] {
        display: none !important;
    }

    /* ── Light Mode Button & Slider accents (Dark Blue) ── */
    /* Primary buttons in light mode: dark blue */
    html:not([data-app-theme="dark"]) button[kind="primary"],
    html:not([data-app-theme="dark"]) button[data-testid="baseButton-primary"],
    html:not([data-app-theme="dark"]) button[data-testid="stBaseButton-primary"],
    html:not([data-app-theme="dark"]) button[kind="primaryFormSubmit"],
    html:not([data-app-theme="dark"]) button[data-testid="baseButton-primaryFormSubmit"],
    html:not([data-app-theme="dark"]) button[data-testid="stBaseButton-primaryFormSubmit"],
    html:not([data-app-theme="dark"]) .stButton > button[kind="primary"],
    html:not([data-app-theme="dark"]) .stButton > button[data-testid="baseButton-primary"],
    [data-app-theme="light"] button[kind="primary"],
    [data-app-theme="light"] button[data-testid="baseButton-primary"],
    [data-app-theme="light"] button[data-testid="stBaseButton-primary"],
    [data-app-theme="light"] button[kind="primaryFormSubmit"],
    [data-app-theme="light"] button[data-testid="baseButton-primaryFormSubmit"],
    [data-app-theme="light"] button[data-testid="stBaseButton-primaryFormSubmit"],
    [data-app-theme="light"] .stButton > button[kind="primary"],
    [data-app-theme="light"] .stButton > button[data-testid="baseButton-primary"] {
        background-color: #1D4ED8 !important;
        border-color: #1D4ED8 !important;
        color: #FFFFFF !important;
    }

    html:not([data-app-theme="dark"]) button[kind="primary"]:hover,
    html:not([data-app-theme="dark"]) button[data-testid="baseButton-primary"]:hover,
    html:not([data-app-theme="dark"]) button[data-testid="stBaseButton-primary"]:hover,
    html:not([data-app-theme="dark"]) button[kind="primaryFormSubmit"]:hover,
    html:not([data-app-theme="dark"]) button[data-testid="baseButton-primaryFormSubmit"]:hover,
    html:not([data-app-theme="dark"]) button[data-testid="stBaseButton-primaryFormSubmit"]:hover,
    html:not([data-app-theme="dark"]) .stButton > button[kind="primary"]:hover,
    html:not([data-app-theme="dark"]) .stButton > button[data-testid="baseButton-primary"]:hover,
    [data-app-theme="light"] button[kind="primary"]:hover,
    [data-app-theme="light"] button[data-testid="baseButton-primary"]:hover,
    [data-app-theme="light"] button[data-testid="stBaseButton-primary"]:hover,
    [data-app-theme="light"] button[kind="primaryFormSubmit"]:hover,
    [data-app-theme="light"] button[data-testid="baseButton-primaryFormSubmit"]:hover,
    [data-app-theme="light"] button[data-testid="stBaseButton-primaryFormSubmit"]:hover,
    [data-app-theme="light"] .stButton > button[kind="primary"]:hover,
    [data-app-theme="light"] .stButton > button[data-testid="baseButton-primary"] {
        background-color: #1E40AF !important;
        border-color: #1E40AF !important;
        color: #FFFFFF !important;
    }

    /* Slider dragging bar in light mode: dark blue */
    html:not([data-app-theme="dark"]) [data-testid="stSlider"] > div:not([data-testid="stWidgetLabel"]),
    html:not([data-app-theme="dark"]) [data-testid="stSlider"] > div:last-child,
    [data-app-theme="light"] [data-testid="stSlider"] > div:not([data-testid="stWidgetLabel"]),
    [data-app-theme="light"] [data-testid="stSlider"] > div:last-child {
        filter: hue-rotate(224deg) brightness(0.85) !important;
    }

    /* Active tab in light mode: dark blue */
    html:not([data-app-theme="dark"]) [data-testid="stTab"][data-selected],
    html:not([data-app-theme="dark"]) [data-testid="stTab"][data-selected] *,
    html:not([data-app-theme="dark"]) [data-testid="stTab"][aria-selected="true"],
    html:not([data-app-theme="dark"]) [data-testid="stTab"][aria-selected="true"] *,
    [data-app-theme="light"] [data-testid="stTab"][data-selected],
    [data-app-theme="light"] [data-testid="stTab"][data-selected] *,
    [data-app-theme="light"] [data-testid="stTab"][aria-selected="true"],
    [data-app-theme="light"] [data-testid="stTab"][aria-selected="true"] * {
        color: #1D4ED8 !important;
    }
    html:not([data-app-theme="dark"]) [data-testid="stTab"] .react-aria-SelectionIndicator,
    html:not([data-app-theme="dark"]) [data-testid="stTabs"] .react-aria-SelectionIndicator,
    [data-app-theme="light"] [data-testid="stTab"] .react-aria-SelectionIndicator,
    [data-app-theme="light"] [data-testid="stTabs"] .react-aria-SelectionIndicator {
        background-color: #1D4ED8 !important;
    }

    /* ================================================================
       DARK MODE — Meridian dark palette: #0B100E / #121A17 / #202E29
       Accent: #1D4ED8 cobalt-blue (buttons/tabs/sliders)
       ================================================================ */

    [data-app-theme="dark"] .stApp {
        background-color: #0B100E !important;
        color: #F4EFE6 !important;
    }
    [data-app-theme="dark"] [data-testid="stHeader"] {
        background-color: #0B100E !important;
    }
    [data-app-theme="dark"] [data-testid="stSidebar"] {
        background-color: #121A17 !important;
        border-right: 1px solid #202E29 !important;
    }
    /* Slider in dark mode: dark blue */
    [data-app-theme="dark"] [data-testid="stSlider"] > div:not([data-testid="stWidgetLabel"]),
    [data-app-theme="dark"] [data-testid="stSlider"] > div:last-child {
        filter: hue-rotate(224deg) brightness(0.85) !important;
    }

    /* Active tab in dark mode: dark blue */
    [data-app-theme="dark"] [data-testid="stTab"][data-selected],
    [data-app-theme="dark"] [data-testid="stTab"][data-selected] *,
    [data-app-theme="dark"] [data-testid="stTab"][aria-selected="true"],
    [data-app-theme="dark"] [data-testid="stTab"][aria-selected="true"] * {
        color: #1D4ED8 !important;
    }
    [data-app-theme="dark"] [data-testid="stTab"] .react-aria-SelectionIndicator,
    [data-app-theme="dark"] [data-testid="stTabs"] .react-aria-SelectionIndicator {
        background-color: #1D4ED8 !important;
    }
    [data-app-theme="dark"] [data-testid="stTab"]:hover,
    [data-app-theme="dark"] [data-testid="stTab"]:hover * {
        color: #1D4ED8 !important;
    }

    /* Primary buttons in dark mode: dark blue */
    [data-app-theme="dark"] button[kind="primary"],
    [data-app-theme="dark"] button[data-testid="baseButton-primary"],
    [data-app-theme="dark"] button[data-testid="stBaseButton-primary"],
    [data-app-theme="dark"] button[kind="primaryFormSubmit"],
    [data-app-theme="dark"] button[data-testid="baseButton-primaryFormSubmit"],
    [data-app-theme="dark"] button[data-testid="stBaseButton-primaryFormSubmit"],
    [data-app-theme="dark"] .stButton > button[kind="primary"],
    [data-app-theme="dark"] .stButton > button[data-testid="baseButton-primary"] {
        background-color: #1D4ED8 !important;
        border-color: #1D4ED8 !important;
        color: #FFFFFF !important;
    }
    [data-app-theme="dark"] button[kind="primary"]:hover,
    [data-app-theme="dark"] button[data-testid="baseButton-primary"]:hover,
    [data-app-theme="dark"] button[data-testid="stBaseButton-primary"]:hover,
    [data-app-theme="dark"] button[kind="primaryFormSubmit"]:hover,
    [data-app-theme="dark"] button[data-testid="baseButton-primaryFormSubmit"]:hover,
    [data-app-theme="dark"] button[data-testid="stBaseButton-primaryFormSubmit"]:hover,
    [data-app-theme="dark"] .stButton > button[kind="primary"]:hover,
    [data-app-theme="dark"] .stButton > button[data-testid="baseButton-primary"]:hover {
        background-color: #1E40AF !important;
        border-color: #1E40AF !important;
        color: #FFFFFF !important;
    }

    /* Dark inputs & selects */
    [data-app-theme="dark"] div[data-baseweb="input"],
    [data-app-theme="dark"] div[data-baseweb="base-input"],
    [data-app-theme="dark"] div[data-baseweb="select"] > div,
    [data-app-theme="dark"] input,
    [data-app-theme="dark"] textarea {
        background-color: #121A17 !important;
        color: #F4EFE6 !important;
        border-color: #202E29 !important;
    }
    [data-app-theme="dark"] div[data-baseweb="input"]:focus-within,
    [data-app-theme="dark"] div[data-baseweb="select"] > div:focus-within {
        border-color: #3B82F6 !important;
    }
    [data-app-theme="dark"] input::placeholder,
    [data-app-theme="dark"] textarea::placeholder { color: #98A6A0 !important; }

    /* Dark dropdown menus */
    [data-app-theme="dark"] div[data-baseweb="popover"],
    [data-app-theme="dark"] ul[data-baseweb="menu"],
    [data-app-theme="dark"] li[data-baseweb="menu-item"] {
        background-color: #121A17 !important; color: #F4EFE6 !important;
    }
    [data-app-theme="dark"] li[data-baseweb="menu-item"]:hover {
        background-color: #202E29 !important;
    }

    /* Dark buttons (secondary) */
    [data-app-theme="dark"] .stButton > button:not([kind="primary"]) {
        background-color: #121A17 !important; color: #F4EFE6 !important;
        border: 1px solid #202E29 !important;
    }
    [data-app-theme="dark"] .stButton > button:not([kind="primary"]):hover {
        background-color: #202E29 !important; border-color: #98A6A0 !important;
    }

    /* Dark custom components */
    [data-app-theme="dark"] .profile-card {
        background: #121A17 !important;
        border-color: #202E29 !important;
    }
    [data-app-theme="dark"] .auth-header {
        background: #121A17 !important;
        border-color: #202E29 !important;
    }
    [data-app-theme="dark"] .result-card,
    [data-app-theme="dark"] .db-card,
    [data-app-theme="dark"] .sync-card {
        background: #121A17 !important;
        border-color: #202E29 !important;
    }
    [data-app-theme="dark"] .result-card:hover,
    [data-app-theme="dark"] .db-card:hover,
    [data-app-theme="dark"] .sync-card:hover {
        border-color: #C86D51 !important;
        box-shadow: 0 8px 30px rgba(0,0,0,0.3) !important;
    }
    [data-app-theme="dark"] .ai-card {
        background: #121A17 !important;
        border-color: #202E29 !important;
        border-left: 4px solid #1D4ED8 !important;
    }
    [data-app-theme="dark"] .info-strip {
        background: #121A17 !important;
        border-color: #202E29 !important;
        border-left-color: #C86D51 !important;
        color: #DFB284 !important;
    }
    [data-app-theme="dark"] .quick-link {
        background: #121A17 !important;
        border-color: #202E29 !important;
        color: #C86D51 !important;
    }
    [data-app-theme="dark"] .quick-link:hover {
        background: #202E29 !important;
    }
    [data-app-theme="dark"] .city-row { border-bottom-color: #202E29 !important; color: #98A6A0 !important; }
    [data-app-theme="dark"] .city-count { color: #C86D51 !important; }
    [data-app-theme="dark"] .section-heading { border-bottom-color: #202E29 !important; color: #F4EFE6 !important; }
    [data-app-theme="dark"] .section-rule { border-top-color: #202E29 !important; }
    [data-app-theme="dark"] [data-testid="stExpander"] {
        background-color: #121A17 !important;
        border-color: #202E29 !important;
    }

    /* Dark mode text overrides */
    [data-app-theme="dark"] .profile-name { color: #F4EFE6 !important; }
    [data-app-theme="dark"] .profile-username { color: #98A6A0 !important; }
    [data-app-theme="dark"] .result-card-name,
    [data-app-theme="dark"] .db-card-name,
    [data-app-theme="dark"] .sync-card-title { color: #F4EFE6 !important; }
    [data-app-theme="dark"] .result-card-sub,
    [data-app-theme="dark"] .db-card-location,
    [data-app-theme="dark"] .sync-card-meta { color: #98A6A0 !important; }
    [data-app-theme="dark"] .meta-label { color: #98A6A0 !important; }
    [data-app-theme="dark"] .meta-value,
    [data-app-theme="dark"] .dish-item { color: #F4EFE6 !important; }
    [data-app-theme="dark"] .ai-card { color: #F4EFE6 !important; }
    [data-app-theme="dark"] .sidebar-footer { color: #98A6A0 !important; }
    [data-app-theme="dark"] .app-header h1 { color: #F4EFE6 !important; }
    [data-app-theme="dark"] .app-header p { color: #98A6A0 !important; }
    [data-app-theme="dark"] .auth-header h2 { color: #F4EFE6 !important; }
    [data-app-theme="dark"] .auth-header p  { color: #98A6A0 !important; }
    [data-app-theme="dark"] .pill-private { background: #3D1810 !important; color: #F4A27A !important; border-color: rgba(200,109,81,0.5) !important; }
    [data-app-theme="dark"] .pill-sync { background: #0A3D2B !important; color: #6EE7B7 !important; border-color: #059669 !important; }
    [data-app-theme="dark"] .pill-guest { background: #1A2420 !important; color: #98A6A0 !important; border-color: #202E29 !important; }
</style>
""", unsafe_allow_html=True)



# ── Helpers ───────────────────────────────────────────────

@st.cache_data(ttl=30)
def load_restaurants():
    if RESTAURANTS_DB.exists():
        try:
            with open(RESTAURANTS_DB, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []


def get_city_list(user_id=None):
    data = load_restaurants()
    if user_id:
        user_data = [r for r in data if r.get("source_user_id") == user_id]
        if user_data:
            cities = sorted(set(r.get("city", "") for r in user_data if r.get("city")))
            if cities:
                return cities
    cities = sorted(set(r.get("city", "") for r in data if r.get("city")))
    return cities if cities else ["Bengaluru", "Coimbatore", "Hyderabad"]


def run_routing_only(location, city, available_hours, dining_minutes=40, user_id=None):
    """Run Phase 2 routing and return annotated restaurants, optionally filtered by user."""
    try:
        from step6_router import filter_restaurants_by_travel_time
        all_rests = load_restaurants()
        if user_id:
            all_rests = [r for r in all_rests if r.get("source_user_id") == user_id]
            if not all_rests:
                return [], f"No restaurants found from your saved playlist. Try switching to 'All users'."
        city_rests = [r for r in all_rests if city.lower() in r.get("city", "").lower()]
        if not city_rests:
            return [], f"No restaurants found for {city}."
        filtered = filter_restaurants_by_travel_time(
            restaurants=city_rests,
            user_location_str=location,
            city=city,
            available_hours=available_hours,
            dining_minutes=dining_minutes
        )
        return filtered, None
    except Exception as e:
        return [], str(e)


def run_full_suggestion(location, city, arrival_time, available_hours, preferences, dining_minutes=40, user_id=None):
    """Run Phase 1 + 2 + Gemini RAG and return the recommendation text, optionally filtered by user."""
    try:
        from step5_suggester import get_food_suggestion
        result = get_food_suggestion(
            current_location=location,
            city=city,
            arrival_time=arrival_time,
            available_hours=available_hours,
            preferences=preferences,
            use_routing=True,
            dining_minutes=dining_minutes,
            user_id=user_id
        )
        return result, None
    except Exception as e:
        return None, str(e)


def render_folium_map(restaurants, user_lat=None, user_lon=None, user_label="Your Location"):
    """Build and display a Folium map without triggering Streamlit reruns."""
    import folium
    from streamlit_folium import st_folium

    center_lat = user_lat or 12.9716
    center_lon = user_lon or 77.5946
    m = folium.Map(location=[center_lat, center_lon], zoom_start=12, tiles="OpenStreetMap")

    # User location marker
    if user_lat:
        folium.Marker(
            location=[user_lat, user_lon],
            popup=f"<b>You are here</b><br>{user_label}",
            tooltip="Your Location",
            icon=folium.Icon(color="blue", icon="person", prefix="fa")
        ).add_to(m)

    # Restaurant markers
    colors = {"feasible": "green", "unknown": "orange", "infeasible": "red"}
    for r in restaurants:
        r_lat = r.get("_lat")
        r_lon = r.get("_lon")
        if not r_lat:
            continue
        is_feasible = r.get("is_feasible", True)
        travel = r.get("travel_minutes_one_way")
        dist   = r.get("distance_km")
        name   = r.get("restaurant_name", "Unknown")
        dishes = ", ".join(r.get("must_try_dishes", [])[:3])
        geo_note = r.get("geo_note", "")

        popup_html = f"""
        <div style='min-width:180px'>
            <b style='color:#1D4ED8'>{name}</b><br>
            <i>{r.get('cuisine_type','')}</i><br>
            {"<br>" + geo_note if geo_note else ""}
            {"<br>" + dishes if dishes else ""}
        </div>"""

        tooltip = f"{name}"
        if travel:
            tooltip += f" | {dist:.1f}km | {travel:.0f}min"

        color = colors["feasible"] if is_feasible else colors["infeasible"]
        if travel is None:
            color = colors["unknown"]

        folium.Marker(
            location=[r_lat, r_lon],
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=tooltip,
            icon=folium.Icon(color=color, icon="cutlery", prefix="fa")
        ).add_to(m)

    # returned_objects=[] prevents streamlit-folium from sending events back,
    # which stops the map from causing Streamlit to rerun and wipe state!
    st_folium(m, use_container_width=True, height=400, returned_objects=[])


# ── Page Header ───────────────────────────────────────────
st.markdown("""
<div class="app-header">
    <h1>Food Discovery Assistant</h1>
    <p>Personalized restaurant recommendations powered by video analysis and real-time travel routing</p>
</div>
""", unsafe_allow_html=True)


# ── Authentication State & Privacy Gate ──────────────────────
if "auth_user" not in st.session_state:
    st.session_state["auth_user"] = None

# Context variables (accessible before and after login)
auth_user = st.session_state.get("auth_user")
is_guest = auth_user.get("is_guest", False) if auth_user else False
user_id = auth_user["user_id"] if (auth_user and not is_guest) else None
user_name = auth_user.get("display_name", auth_user.get("username", "User")) if auth_user else None

# ── Sidebar (Always Rendered) ─────────────────────────────────
with st.sidebar:
    if auth_user:
        _initials = user_name[0].upper() if user_name else "U"
        st.markdown(f"""
        <div class="profile-card">
            <div class="profile-avatar">{_initials}</div>
            <div class="profile-name">{user_name}</div>
            <div class="profile-username">@{auth_user.get('username', '')}</div>
            <div style="margin-top: 0.6rem;">
                {"<span class='status-pill pill-private'>Private Profile</span>" if not is_guest else "<span class='status-pill pill-guest'>Guest Mode</span>"}
                {"<br><span class='status-pill pill-sync' style='margin-top:0.3rem; display:inline-block;'>Auto-Sync Active</span>" if not is_guest else ""}
            </div>
        </div>
        """, unsafe_allow_html=True)


        if st.button("Sign Out", use_container_width=True, icon=":material/logout:"):
            st.session_state["auth_user"] = None
            st.session_state["search_results"] = None
            st.rerun()

        st.divider()

        db = load_restaurants()
        if is_guest:
            user_db = [r for r in db if not r.get("source_user_id")]
        else:
            user_db = [r for r in db if r.get("source_user_id") == user_id]

        st.metric("Saved Places", len(user_db))

        city_counts = {}
        for r in user_db:
            c = r.get("city", "Unknown")
            city_counts[c] = city_counts.get(c, 0) + 1

        if city_counts:
            city_rows_html = "".join(
                f"<div class='city-row'><span>{c}</span><span class='city-count'>{n}</span></div>"
                for c, n in sorted(city_counts.items())
            )
            st.markdown(city_rows_html, unsafe_allow_html=True)

        st.divider()

    else:
        st.markdown("""
        <div class="profile-card">
            <div class="profile-avatar">G</div>
            <div class="profile-name">Guest Mode</div>
            <div class="profile-username">Sign in to sync playlists</div>
        </div>
        """, unsafe_allow_html=True)


        st.divider()

    st.markdown(
        """<div class="sidebar-footer">
        Powered by <strong>Gemini AI</strong> and <strong>Whisper</strong><br>
        Food Discovery Assistant
        </div>""",
        unsafe_allow_html=True
    )


# ── Auth Screen (If Not Signed In) ────────────────────────────
if not auth_user:
    st.markdown("""
    <div class="auth-header">
        <h2>Private Account Login</h2>
        <p>
            Sign in with your private account. Your saved YouTube playlists, videos, and food
            recommendations are strictly isolated to your profile. Other users cannot view or
            access your saved places.
        </p>
    </div>
    """, unsafe_allow_html=True)

    auth_tab1, auth_tab2, auth_tab3 = st.tabs(["Sign In", "Create Account", "Guest Access"])

    with auth_tab1:
        st.markdown("#### Access Your Private Food Playlist")
        col_l1, col_l2 = st.columns([1, 1])
        with col_l1:
            login_id = st.text_input("Username or Email", key="login_id_input")
        with col_l2:
            login_pwd = st.text_input("Password", type="password", key="login_pwd_input")

        if st.button("Sign In", type="primary", use_container_width=True, icon=":material/login:"):
            if not login_id or not login_pwd:
                st.error("Please enter both username/email and password.")
            else:
                from youtube_account_sync import login_user
                ok, msg, u = login_user(login_id, login_pwd)
                if ok:
                    st.session_state["auth_user"] = u
                    st.success(f"Welcome back, {u['display_name']}!")
                    st.rerun()
                else:
                    st.error(msg)

    with auth_tab2:
        st.markdown("#### Create a New Private Account")
        st.caption("Each account gets an isolated database synced automatically from your YouTube food playlists.")
        col_r1, col_r2, col_r3 = st.columns([1, 1, 1])
        with col_r1:
            reg_name = st.text_input("Your Name", placeholder="e.g. Lohith", key="reg_name_input")
        with col_r2:
            reg_id = st.text_input("Username or Email", placeholder="e.g. lohith@gmail.com", key="reg_id_input")
        with col_r3:
            reg_pwd = st.text_input("Choose Password", type="password", key="reg_pwd_input")

        if st.button("Create Account", type="primary", use_container_width=True, icon=":material/person_add:"):
            from youtube_account_sync import register_user
            ok, msg, u = register_user(reg_id, reg_pwd, reg_name)
            if ok:
                st.session_state["auth_user"] = u
                st.success("Account created successfully! Logging you in...")
                st.rerun()
            else:
                st.error(msg)

    with auth_tab3:
        st.markdown("#### Explore Public Database")
        st.caption("Browse pre-loaded seed restaurants without linking a personal playlist.")
        if st.button("Continue as Guest", use_container_width=True, icon=":material/visibility:"):
            st.session_state["auth_user"] = {
                "user_id": "guest_public",
                "username": "guest",
                "display_name": "Guest (Public)",
                "is_guest": True,
                "linked_playlists": []
            }
            st.rerun()

    st.stop()  # Stop rendering so unauthorized users cannot access any data!


# ── Tabs ──────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs([
    ":material/search: Search",
    ":material/add_circle: Add",
    ":material/storage: Database"
])


# ═══════════════════════════════════════════════════════════
# TAB 1: SEARCH (FIND FOOD)
# ═══════════════════════════════════════════════════════════
with tab1:
    st.markdown("### Enter Your Location")

    if not is_guest:
        st.markdown(
            f"""<div class="info-strip">
            <strong>Private Mode:</strong> Recommendations are based exclusively on
            <strong>{user_name}</strong>'s saved video library.
            </div>""",
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            """<div class="info-strip">
            <strong>Public Mode:</strong> Recommendations are based on the public restaurant database.
            </div>""",
            unsafe_allow_html=True
        )

    col1, col2 = st.columns([1, 1])

    with col1:
        city = st.selectbox(
            "City",
            options=get_city_list(user_id=user_id),
            help="Select the city you are visiting"
        )
        location = st.text_input(
            "Current location",
            placeholder="e.g. Bengaluru Railway Station, Majestic",
            help="Enter a landmark, area, or address"
        )
        preferences = st.text_input(
            "Dietary preferences (optional)",
            placeholder="e.g. vegetarian, budget meal, non-spicy",
        )

    with col2:
        arrival_time = st.time_input(
            "Current time",
            value=None,
            help="What time is it right now?"
        )
        avail_val = st.session_state.get("slider_avail_hours", 2.0)
        available_hours = st.slider(
            f"Available time (hours): {avail_val:.2f}",
            min_value=0.5,
            max_value=5.0,
            value=2.0,
            step=0.5,
            key="slider_avail_hours",
            help="Total time including travel to and from the restaurant"
        )
        dining_val = st.session_state.get("slider_dining_mins", 40)
        dining_minutes = st.slider(
            f"Dining time to reserve (minutes): {dining_val}",
            min_value=20,
            max_value=90,
            value=40,
            step=5,
            key="slider_dining_mins",
            help="How long you plan to sit and eat"
        )

    st.divider()

    if "search_results" not in st.session_state:
        st.session_state["search_results"] = None

    if st.button(
        "Get Recommendations",
        type="primary",
        use_container_width=True,
        icon=":material/search:"
    ):
        if not location.strip():
            st.error("Please enter your current location.")
        else:
            arrival_str = arrival_time.strftime("%I:%M %p") if arrival_time else "Now"

            # ── Step 1: Routing ───────────────────────────────
            with st.spinner(f"Calculating travel times from '{location}' to restaurants in {city}..."):
                routed, err = run_routing_only(location, city, available_hours, dining_minutes, user_id=user_id)

            if err:
                st.error(f"Routing error: {err}")
            elif not routed:
                st.warning(f"No restaurants found for {city}. Add some via the 'Add' tab.")
            else:
                # ── Step 2: Crowd estimation + Google Maps links ──
                try:
                    from step7_crowd import enrich_restaurants_with_crowd_and_maps
                    routed = enrich_restaurants_with_crowd_and_maps(
                        routed, arrival_str, location, city
                    )
                except Exception as crowd_err:
                    st.caption(f"Crowd estimation unavailable: {crowd_err}")

                # ── Step 3: Opening Hours Check ──
                try:
                    from step8_hours import enrich_restaurants_with_hours
                    routed = enrich_restaurants_with_hours(routed, arrival_str)
                except Exception as hrs_err:
                    st.caption(f"Opening hours check unavailable: {hrs_err}")

                # ── Step 4: Coordinates for map ──
                u_lat, u_lon = None, None
                try:
                    from step6_router import geocode_user_location, geocode_restaurant
                    u_lat, u_lon = geocode_user_location(location, city)
                    for r in routed:
                        rl, rlon = geocode_restaurant(r)
                        r["_lat"] = rl
                        r["_lon"] = rlon
                except Exception:
                    pass

                # ── Step 5: AI Recommendation ──
                with st.spinner("Asking Gemini to select the best option for you..."):
                    suggestion, err2 = run_full_suggestion(
                        location, city, arrival_str, available_hours, preferences, dining_minutes,
                        user_id=user_id
                    )

                # Store in session state so reruns never wipe results
                st.session_state["search_results"] = {
                    "routed": routed,
                    "suggestion": suggestion,
                    "err2": err2,
                    "location": location,
                    "city": city,
                    "arrival_str": arrival_str,
                    "available_hours": available_hours,
                    "dining_minutes": dining_minutes,
                    "u_lat": u_lat,
                    "u_lon": u_lon,
                }

    # ── Display Results (Persistent across reruns) ──
    results = st.session_state.get("search_results")
    if results:
        res_loc      = results["location"]
        res_city     = results["city"]
        res_hours    = results["available_hours"]
        res_dining   = results["dining_minutes"]
        res_routed   = results["routed"]
        res_suggestion = results["suggestion"]
        res_arrival  = results["arrival_str"]

        st.markdown(
            f'<div class="section-heading">Travel Times from {res_loc}</div>',
            unsafe_allow_html=True
        )
        st.caption(
            f"Time budget: **{res_hours}h total** = "
            f"round-trip travel + **{res_dining} min dining** | "
            f"Max one-way: **{(res_hours*60 - res_dining)/2:.0f} min**"
        )

        # ── Build routing table ──
        table_data = []
        for r in res_routed:
            t = r.get("total_time_minutes")
            d = r.get("distance_km")
            tw = r.get("travel_minutes_one_way")
            feasible = r.get("is_feasible", True)
            crowd = r.get("crowd_at_arrival", {})
            hrs = r.get("opening_status", {})

            if t is not None:
                status = "Reachable" if feasible else "Too far"
                total_str = f"{t:.0f} min"
                dist_str = f"{d:.1f} km"
                travel_str = f"{tw:.0f} min"
            else:
                status = "Location approximate"
                total_str = dist_str = travel_str = "—"

            crowd_str = f"{crowd.get('crowd_level', '—')}" if crowd else "—"
            hours_str = f"{hrs.get('status_label', 'Unknown')}" if hrs else "Unknown"

            table_data.append({
                "Restaurant": r.get("restaurant_name", "Unknown"),
                "Area": r.get("area_or_locality") or "—",
                "Distance": dist_str,
                "One-way": travel_str,
                "Total time": total_str,
                "Open": hours_str,
                "Crowd": crowd_str,
                "Status": status
            })

        import pandas as pd
        df = pd.DataFrame(table_data)
        st.dataframe(df, use_container_width=True, hide_index=True)

        # ── Quick Links ──
        st.markdown(
            '<div class="section-heading">Quick Links</div>',
            unsafe_allow_html=True
        )
        maps_cols = st.columns(min(len(res_routed), 3))
        for idx, r in enumerate(res_routed[:6]):
            col = maps_cols[idx % len(maps_cols)]
            name = r.get("restaurant_name", "Unknown")
            maps_link = r.get("google_maps_link", "")
            dir_link = r.get("google_maps_directions", "")
            crowd = r.get("crowd_at_arrival", {})
            hrs = r.get("opening_status", {})
            with col:
                st.markdown(f"**{name}**")
                if hrs:
                    st.caption(f"{hrs.get('status_label', 'Unknown')} — {hrs.get('hours_note', '')[:50]}")
                links_html = ""
                if maps_link:
                    links_html += f"<a class='quick-link' href='{maps_link}' target='_blank'>View on Maps</a>"
                if dir_link:
                    links_html += f"<a class='quick-link' href='{dir_link}' target='_blank'>Get Directions</a>"
                if links_html:
                    st.markdown(links_html, unsafe_allow_html=True)
                if crowd:
                    st.caption(f"{crowd.get('crowd_description', '')} crowd")
                    if crowd.get("tip"):
                        st.caption(crowd["tip"])

        # ── Closed Restaurant Warnings ──
        closed = [
            r for r in res_routed
            if r.get("opening_status", {}).get("is_open") is False
            and r.get("opening_status", {}).get("confidence") == "confirmed"
        ]
        likely_closed = [
            r for r in res_routed
            if r.get("opening_status", {}).get("is_open") is False
            and r.get("opening_status", {}).get("confidence") == "heuristic"
        ]
        if closed:
            for r in closed:
                hrs = r["opening_status"]
                st.error(
                    f"**{r['restaurant_name']} is currently closed.** "
                    f"{hrs.get('hours_note', '')} — Please plan accordingly."
                )
        if likely_closed:
            with st.expander(f"{len(likely_closed)} restaurant(s) may be closed at this time"):
                for r in likely_closed:
                    hrs = r["opening_status"]
                    st.warning(f"**{r['restaurant_name']}**: {hrs.get('hours_note', '')} (estimated from meal type)")

        # ── Map ──
        st.markdown(
            '<div class="section-heading">Map</div>',
            unsafe_allow_html=True
        )
        try:
            render_folium_map(res_routed, results.get("u_lat"), results.get("u_lon"), res_loc)
        except Exception as map_err:
            st.info(f"Map unavailable: {map_err}")

        # ── AI Recommendation ──
        st.divider()
        st.markdown(
            '<div class="section-heading">AI Recommendation</div>',
            unsafe_allow_html=True
        )
        st.caption(
            "Gemini analyzes your pre-filtered restaurants and selects the best option "
            "based on opening hours, time of day, cuisine, crowd levels, and your preferences."
        )

        if results.get("err2"):
            st.error(f"AI error: {results['err2']}")
        elif res_suggestion:
            st.markdown(
                f'<div class="ai-card">{res_suggestion}</div>',
                unsafe_allow_html=True
            )
            out = DATA_DIR / "last_suggestion.txt"
            out.write_text(
                f"Location: {res_loc} | {res_city}\nTime: {res_arrival} | {res_hours}h\n\n{res_suggestion}",
                encoding="utf-8"
            )
            st.caption("Suggestion saved to data/last_suggestion.txt")


# ═══════════════════════════════════════════════════════════
# TAB 2: ADD RESTAURANT & SYNC PLAYLISTS
# ═══════════════════════════════════════════════════════════
with tab2:
    tab2_sub1, tab2_sub2 = st.tabs([
        ":material/sync: Playlist Sync",
        ":material/play_circle: Single Video"
    ])

    with tab2_sub1:
        if is_guest:
            st.warning("This feature requires a private account. Please sign in or create an account to link your YouTube food playlist and receive personalized recommendations.")
            st.stop()

        st.markdown(f"### YouTube Playlist Auto-Sync — {user_name}")
        st.markdown(
            "Link your YouTube food playlist once. Whenever you save a new food video to this "
            "playlist on YouTube, the background sync engine will automatically detect it and "
            "add it to your database within 60 seconds — no manual action needed."
        )

        # ── Show currently monitored playlists ──
        linked_pls = auth_user.get("linked_playlists", [])
        if linked_pls:
            st.markdown("#### Monitored Playlists")
            for pl in linked_pls:
                known_count = len(pl.get("known_video_ids", []))
                st.markdown(f"""
                <div class="sync-card">
                    <div class="sync-card-title">{pl.get('name', 'Food Playlist')}</div>
                    <div class="sync-card-meta">
                        <span class="status-pill pill-sync">Auto-Sync Active</span>
                        &nbsp; {known_count} videos monitored &nbsp;&middot;&nbsp;
                        Last checked: {pl.get('last_synced', 'Recently')}
                    </div>
                </div>
                """, unsafe_allow_html=True)

            col_chk1, col_chk2 = st.columns([1, 1])
            with col_chk1:
                if st.button("Check for New Videos Now", use_container_width=True, icon=":material/refresh:"):
                    from youtube_account_sync import auto_sync_user_playlists
                    with st.spinner("Checking your playlist for new videos..."):
                        new_count = auto_sync_user_playlists(user_id)
                        if new_count > 0:
                            st.success(f"Found and queued {new_count} newly added video(s) from your playlist.")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.info("Your playlist is up to date. No new videos were added since last check.")

        st.markdown("#### Link a YouTube Food Playlist")
        st.caption(
            "Paste any YouTube Food Playlist link or Watch Later link. "
            "All current videos will be ingested and future additions will be synced automatically."
        )

        sync_playlist_url = st.text_input(
            "YouTube Playlist URL",
            placeholder="https://www.youtube.com/playlist?list=PL... or WL",
            help="Paste the link to your saved food playlist or Watch Later"
        )

        if st.button(
            "Link Playlist and Start Auto-Sync",
            type="primary",
            use_container_width=True,
            icon=":material/link:"
        ):
            if not sync_playlist_url.strip():
                st.error("Please enter a YouTube Playlist URL.")
            else:
                try:
                    from youtube_account_sync import (
                        extract_playlist_videos_ytdlp,
                        link_user_playlist,
                        sync_videos_to_backend
                    )

                    with st.status("Accessing YouTube playlist and collecting videos...", expanded=True) as status_box:
                        status_box.write("Step 1: Scanning playlist videos...")
                        pl_title, videos = extract_playlist_videos_ytdlp(sync_playlist_url)

                        if not videos:
                            status_box.update(label="No videos found in playlist", state="error")
                            st.error("Could not find any videos in this playlist. Please ensure the link is valid and the playlist is public or unlisted.")
                        else:
                            status_box.write(f"Found {len(videos)} videos in playlist '{pl_title}'.")
                            status_box.write(f"Registering playlist to private profile: {user_name}...")

                            video_ids = [v["video_id"] for v in videos]
                            updated_user = link_user_playlist(user_id, sync_playlist_url, pl_title, video_ids)
                            st.session_state["auth_user"] = updated_user
                            auth_user = updated_user

                            status_box.write("Step 2: Queuing videos for transcription and AI extraction...")
                            sync_videos_to_backend(
                                videos=videos,
                                user_id=user_id,
                                user_name=user_name,
                                playlist_name=pl_title
                            )

                            status_box.update(label="Playlist linked and auto-sync active.", state="complete", expanded=False)
                            st.success(
                                f"Successfully linked {len(videos)} videos from '{pl_title}'. "
                                "Auto-sync is now monitoring this playlist every 60 seconds."
                            )
                            st.rerun()
                except Exception as sync_err:
                    st.error(f"Sync error: {sync_err}")

        st.divider()

        # ── Google Account OAuth Login ──
        st.markdown("#### Google Account Sign-In (OAuth)")
        st.caption("Sign in with your Google Account to automatically browse and select your YouTube food playlists.")

        try:
            from youtube_account_sync import (
                is_google_oauth_configured,
                authenticate_google_account,
                get_user_youtube_playlists,
                fetch_playlist_videos_via_api,
                sync_videos_to_backend
            )

            if not is_google_oauth_configured():
                with st.expander("How to enable Google Account Sign-In with OAuth"):
                    st.markdown("""
                    To use the native Google login button:
                    1. Go to [Google Cloud Console](https://console.cloud.google.com/)
                    2. Enable **YouTube Data API v3**
                    3. Create **OAuth 2.0 Client ID** (Desktop Application)
                    4. Download JSON and save it as `client_secret.json` in this project folder.

                    *(You can also use the Playlist Sync above without any Google Cloud setup.)*
                    """)
            else:
                if st.button("Sign in with Google Account", use_container_width=True, icon=":material/login:"):
                    try:
                        with st.spinner("Opening Google sign-in window in your browser..."):
                            auth_res = authenticate_google_account()
                            st.session_state["oauth_user"] = auth_res
                            st.session_state["active_user_filter"] = auth_res["user_id"]
                            st.session_state["active_user_name"] = auth_res["user_name"]
                            st.success(f"Connected as **{auth_res['user_name']}** ({auth_res['email']}).")
                            st.rerun()
                    except Exception as oauth_err:
                        st.error(f"Google sign-in error: {oauth_err}")

                # If logged in via OAuth, display user playlists
                oauth_user = st.session_state.get("oauth_user")
                if oauth_user:
                    u_id = oauth_user["user_id"]
                    u_name = oauth_user["user_name"]
                    st.success(f"Connected Google Account: **{u_name}** ({oauth_user.get('email')})")

                    with st.spinner("Fetching your YouTube playlists..."):
                        user_playlists = get_user_youtube_playlists(u_id)

                    if user_playlists:
                        pl_titles = [f"{p['title']} ({p['item_count']} videos)" for p in user_playlists]
                        chosen_idx = st.selectbox("Select your Food Playlist", range(len(pl_titles)), format_func=lambda i: pl_titles[i])
                        chosen_pl = user_playlists[chosen_idx]

                        if st.button(f"Sync Playlist '{chosen_pl['title']}'", type="primary"):
                            with st.status(f"Fetching videos from {chosen_pl['title']}...", expanded=True) as status_box:
                                vids = fetch_playlist_videos_via_api(u_id, chosen_pl["id"])
                                status_box.write(f"Found {len(vids)} videos in playlist.")
                                sync_videos_to_backend(vids, u_id, u_name, chosen_pl["title"])
                                status_box.update(label="Videos queued for extraction.", state="complete")
                                st.success("All videos queued. Recommendations will now be personalized to this playlist.")
                                st.rerun()
                    else:
                        st.info("No public or personal playlists found on this YouTube account.")
        except Exception as oauth_check_err:
            st.caption(f"OAuth module standby: {oauth_check_err}")

    # ── Sub-Tab 2: Add Single Video URL ──
    with tab2_sub2:
        col_ext_1, col_ext_2 = st.columns([2.5, 1.5])
        with col_ext_1:
            st.markdown("### Add a Restaurant from a Single Video")
            st.markdown(
                "Paste a YouTube video link below to transcribe and extract food spots using Gemini."
            )
        with col_ext_2:
            try:
                import requests
                api_res = requests.get("http://127.0.0.1:8000/api/health", timeout=0.5)
                if api_res.status_code == 200:
                    st.markdown("<span class='api-online'>Ingestion API: Online</span>", unsafe_allow_html=True)
                else:
                    st.markdown("<span class='api-offline'>Ingestion API: Standby</span>", unsafe_allow_html=True)
            except Exception:
                st.markdown("<span class='api-offline'>Ingestion API: Run api_server.py to enable</span>", unsafe_allow_html=True)

        with st.form("add_single_video_form"):
            single_user = st.text_input(
                "Associate with Account / User Profile",
                value=user_name if not is_guest else "",
                placeholder="e.g. Lohith or leave blank for Public",
                disabled=not is_guest
            )
            video_url = st.text_input(
                "Video URL",
                placeholder="https://www.youtube.com/shorts/xxxx or https://www.youtube.com/watch?v=xxxx"
            )
            submitted = st.form_submit_button(
                "Process Video",
                type="primary",
                use_container_width=True,
                icon=":material/play_arrow:"
            )

        if submitted:
            if not video_url.strip():
                st.error("Please paste a video URL.")
            else:
                try:
                    with st.status("Processing video...", expanded=True) as status_box:
                        status_box.write("Step 1: Downloading audio and reading video metadata...")
                        status_box.write("Step 2: Auto-detecting city and video type...")
                        status_box.write("Step 3: Transcribing audio with Whisper...")
                        status_box.write("Step 4: Extracting restaurant details with Gemini AI...")

                        u_clean = user_name if not is_guest else (single_user.strip() if single_user.strip() else None)
                        uid_clean = user_id if not is_guest else (u_clean.lower().replace(" ", "_") if u_clean else None)

                        cmd = [
                            str(BASE_DIR / "venv" / "Scripts" / "python.exe"),
                            str(BASE_DIR / "batch_process.py"),
                            "--url", video_url,
                            "--city", "auto",
                            "--type", "auto"
                        ]

                        result = subprocess.run(
                            cmd,
                            cwd=str(BASE_DIR),
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=600
                        )

                        if result.returncode == 0:
                            # If a user was specified, tag the newly added restaurant
                            if u_clean:
                                from batch_process import load_restaurants, save_restaurants
                                cur_db = load_restaurants()
                                modified = False
                                for r in cur_db:
                                    if r.get("source_url") == video_url and not r.get("source_user_name"):
                                        r["source_user_id"] = uid_clean
                                        r["source_user_name"] = u_clean
                                        modified = True
                                if modified:
                                    save_restaurants(cur_db)

                            status_box.update(label="Processing complete.", state="complete", expanded=False)
                            st.success("Restaurant(s) successfully added to the database.")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            status_box.update(label="Processing failed", state="error", expanded=True)
                            st.error("Processing failed. Check the error log below:")
                            st.code(result.stderr[-2000:] if result.stderr else result.stdout[-2000:])
                except Exception as ex:
                    st.error(f"Error: {ex}")


# ═══════════════════════════════════════════════════════════
# TAB 3: BROWSE DATABASE
# ═══════════════════════════════════════════════════════════
with tab3:
    if not is_guest:
        st.markdown(f"### {user_name}'s Restaurant Database")
        st.caption(
            f"Private mode: Showing exclusively the places discovered from {user_name}'s "
            "saved YouTube playlist. Other users cannot access or view your saved places."
        )
    else:
        st.markdown("### Public Restaurant Database")
        st.caption("Browsing pre-loaded public restaurants.")

    all_data = load_restaurants()
    if is_guest:
        data = [r for r in all_data if not r.get("source_user_id")]
    else:
        data = [r for r in all_data if r.get("source_user_id") == user_id]

    if not data:
        if not is_guest:
            st.info(
                "You have not synced any restaurants to your profile yet. "
                "Go to the Add tab to link your YouTube food playlist."
            )
        else:
            st.info("No restaurants found in the database.")
    else:
        # ── Filter Bar ──
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            filter_city = st.selectbox(
                "City",
                options=["All"] + sorted(set(r.get("city", "") for r in data))
            )
        with col_f2:
            filter_diet = st.selectbox(
                "Diet",
                options=["All", "Vegetarian", "Non-Vegetarian"]
            )
        with col_f3:
            filter_meal = st.selectbox(
                "Meal Type",
                options=["All", "breakfast", "lunch", "dinner", "snacks"]
            )

        # ── Apply filters ──
        filtered = data
        if filter_city != "All":
            filtered = [r for r in filtered if r.get("city") == filter_city]

        if filter_diet == "Vegetarian":
            filtered = [r for r in filtered if "veg" in r.get("cuisine_type", "").lower()
                        and "non" not in r.get("cuisine_type", "").lower()]
        elif filter_diet == "Non-Vegetarian":
            filtered = [r for r in filtered if "non" in r.get("cuisine_type", "").lower()
                        or any(m in r.get("cuisine_type","").lower()
                               for m in ["chicken","mutton","meat","fish"])]
        if filter_meal != "All":
            def _meal_match(r, meal):
                mt = r.get("meal_type", [])
                if isinstance(mt, list):
                    return meal in mt
                return meal in str(mt).lower()
            filtered = [r for r in filtered if _meal_match(r, filter_meal)]

        user_tag = f" from {user_name}'s saved videos" if not is_guest else ""
        st.caption(f"Showing {len(filtered)} of {len(data)} restaurants{user_tag}")

        st.divider()

        # ── Restaurant Cards ──
        for r in filtered:
            name      = r.get("restaurant_name", "Unknown")
            city_val  = r.get("city", "")
            area      = r.get("area_or_locality") or ""
            cuisine   = r.get("cuisine_type", "")
            raw_meals = r.get("meal_type", [])
            meal_list = raw_meals if isinstance(raw_meals, list) else [raw_meals] if raw_meals else []
            meals     = ", ".join(meal_list)
            raw_dishes = r.get("must_try_dishes", [])
            dishes    = raw_dishes if isinstance(raw_dishes, list) else [raw_dishes] if raw_dishes else []
            notes     = r.get("special_notes") or ""
            raw_rating = r.get("rating", {})
            sentiment = raw_rating.get("reviewer_sentiment", "") if isinstance(raw_rating, dict) else ""
            src_url   = r.get("source_url", "")
            raw_price = r.get("price_range", {})
            price     = (raw_price.get("description") or "") if isinstance(raw_price, dict) else ""
            verified  = r.get("location_verified")
            crowd     = r.get("crowd_level", {})
            source_user = r.get("source_user_name")

            # Determine badges
            verified_badge = "<span class='badge badge-verified'>Verified</span>" if verified is True else ""
            sentiment_badge_map = {
                "Positive": "<span class='badge badge-positive'>Positive</span>",
                "Mixed":    "<span class='badge badge-mixed'>Mixed</span>",
                "Negative": "<span class='badge badge-negative'>Negative</span>",
            }
            sentiment_badge = sentiment_badge_map.get(sentiment, "")

            location_line = city_val
            if area:
                location_line += f" &middot; {area}"

            # Meta grid rows
            meta_rows = ""
            if cuisine:
                meta_rows += f"<span class='meta-label'>Cuisine</span><span class='meta-value'>{cuisine}</span>"
            if meals:
                meta_rows += f"<span class='meta-label'>Meal Type</span><span class='meta-value'>{meals}</span>"
            if price:
                meta_rows += f"<span class='meta-label'>Price Range</span><span class='meta-value'>{price.capitalize()}</span>"
            if sentiment:
                meta_rows += f"<span class='meta-label'>Sentiment</span><span class='meta-value'>{sentiment}</span>"

            dish_items = "".join(f"<div class='dish-item'>&bull; {d}</div>" for d in dishes)
            notes_html = f"<div style='font-size:0.84rem;color:#64748B;margin-top:0.4rem;'>{notes}</div>" if notes else ""

            crowd_html = ""
            if crowd.get("usually_crowded_at"):
                crowd_html += f"<div style='font-size:0.82rem;color:#D97706;margin-top:0.3rem;'>Peak: {crowd['usually_crowded_at']}</div>"
            if crowd.get("best_time_to_visit"):
                crowd_html += f"<div style='font-size:0.82rem;color:#16A34A;'>Best time: {crowd['best_time_to_visit']}</div>"

            # Action links
            link_html = ""
            if src_url:
                link_html += f"<a class='quick-link' href='{src_url}' target='_blank'>Watch Source Video</a>"
            try:
                from step7_crowd import get_google_maps_link
                maps_url = get_google_maps_link(r)
                link_html += f"<a class='quick-link' href='{maps_url}' target='_blank'>Open in Google Maps</a>"
            except Exception:
                pass

            saved_by_html = f"<div style='font-size:0.76rem;color:#94A3B8;margin-top:0.4rem;'>Saved by: {source_user}</div>" if source_user else ""

            # Render card inside expander for a clean collapsible list
            with st.expander(f"**{name}** — {city_val}{', ' + area if area else ''}", expanded=False):
                st.markdown(f"""
                <div class="db-card">
                    <div class="db-card-header">
                        <div>
                            <div class="db-card-name">{name}{verified_badge}{sentiment_badge}</div>
                            <div class="db-card-location">{location_line}</div>
                        </div>
                    </div>
                    <hr class="section-rule">
                    <div class="meta-grid">{meta_rows}</div>
                    {"<hr class='section-rule'>" if dishes else ""}
                    {"<div style='font-size:0.82rem;font-weight:600;color:#64748B;margin-bottom:0.3rem;'>Recommended Dishes</div>" + dish_items if dishes else ""}
                    {"<hr class='section-rule'>" if notes else ""}
                    {notes_html}
                    {"<hr class='section-rule'>" if crowd_html else ""}
                    {crowd_html}
                    {"<hr class='section-rule'>" if link_html else ""}
                    <div style="margin-top:0.4rem;">{link_html}</div>
                    {saved_by_html}
                </div>
                """, unsafe_allow_html=True)
