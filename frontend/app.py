# frontend/app.py
import streamlit as st
import requests
import sys, os

st.set_page_config(
    page_title="AI Content Studio",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Base ── */
.main .block-container { padding-top: 2rem; padding-bottom: 2rem; max-width: 1100px; }

/* ── Hide anchor link icons on headings (Streamlit adds these) ── */
h1 a, h2 a, h3 a { display: none !important; }
[data-testid="StyledLinkIconContainer"] { display: none !important; }
.css-ue6h4q { display: none !important; }
a[href^="#"] svg { display: none !important; }

/* ── Hide only the auto-generated page links, keep sidebar visible ── */
[data-testid="stSidebarNavItems"] { display: none !important; }
[data-testid="stSidebarNavSeparator"] { display: none !important; }
section[data-testid="stSidebarNav"] { display: none !important; }

/* ── Hide Streamlit default chrome ── */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }

/* ── Sidebar styling ── */
[data-testid="stSidebar"] {
    background: #0d0d14 !important;
    border-right: 1px solid #1a1a28;
}
[data-testid="stSidebar"] > div:first-child {
    padding-top: 0;
}

/* ── Sidebar nav buttons — override Streamlit's default button style ── */
[data-testid="stSidebar"] .stButton > button {
    background: transparent !important;
    border: none !important;
    border-radius: 8px !important;
    color: #6c6c8a !important;
    font-size: 0.85rem !important;
    font-weight: 500 !important;
    text-align: left !important;
    padding: 9px 14px !important;
    margin: 1px 0 !important;
    transition: all 0.15s !important;
    box-shadow: none !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: #1a1a28 !important;
    color: #b4b4cc !important;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: #1e1e2e !important;
    color: #e2e2f0 !important;
    border-left: 2px solid #7c6af7 !important;
}

/* ── Metric cards ── */
[data-testid="stMetric"] {
    background: #16161f;
    border: 1px solid #1e1e2e;
    border-radius: 10px;
    padding: 14px !important;
}
[data-testid="stMetricValue"] { font-size: 1.3rem; font-weight: 700; }

/* ── Expander ── */
[data-testid="stExpander"] { border: 1px solid #1e1e2e; border-radius: 8px; }

/* ── Primary buttons ── */
.stButton > button[kind="primary"] {
    background: #7c6af7 !important;
    border: none !important;
    color: white !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
}
.stButton > button[kind="primary"]:hover {
    background: #6b59e6 !important;
}

/* ── Content blocks ── */
.content-block {
    background: #13131c;
    border: 1px solid #1e1e2e;
    border-radius: 10px;
    padding: 1.2rem;
    line-height: 1.7;
    white-space: pre-wrap;
    font-size: 0.875rem;
}
</style>
""", unsafe_allow_html=True)

# ── Session state defaults ────────────────────────────────────────────────────
# ── Resolve API key from Streamlit secrets / env — never hardcode ──────────
def _read_env_file(path) -> str:
    """
    Read a .env file robustly. Some Windows editors (Notepad, older VS Code
    configs) save with a UTF-8 BOM, which breaks a plain utf-8 read on the
    first line. Try utf-8-sig first (strips BOM if present), fall back to
    utf-8, and never crash the app over an encoding quirk.
    """
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, Exception):
            continue
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _get_api_key() -> str:
    """
    Load API key in priority order:
      1. st.secrets["MASTER_API_KEY"]  — .streamlit/secrets.toml or HF Spaces secrets
      2. os.environ["MASTER_API_KEY"]  — shell / Docker env
      3. .env file in project root      — local development fallback
      4. Empty string                   — shows clear 401 error

    NEVER hardcode the key in source.
    """
    import os
    from pathlib import Path

    # Priority 1: Streamlit secrets (production / HF Spaces)
    try:
        val = st.secrets.get("MASTER_API_KEY", "")
        if val:
            return val
    except Exception:
        pass

    # Priority 2: Environment variable (Docker / shell export)
    val = os.environ.get("MASTER_API_KEY", "")
    if val:
        return val

    # Priority 3: Read .env file directly (local dev — dotenv not auto-loaded in frontend)
    for env_path in [
        Path(__file__).parent.parent / ".env",   # project root
        Path(__file__).parent / ".env",           # frontend dir
        Path(".env"),                              # cwd
    ]:
        if env_path.exists():
            text = _read_env_file(env_path)
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("MASTER_API_KEY=") and not line.startswith("#"):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
                        return val
    return ""


def _get_backend_url() -> str:
    """
    Read backend URL. Priority:
    1. BACKEND_URL environment variable (set by start.sh or Docker env)
    2. st.secrets (HF Spaces / secrets.toml)
    3. .env file (local dev)
    4. Default: localhost:8000 (single-container deploy, always correct)
    """
    import os
    from pathlib import Path

    # Check env var FIRST — start.sh exports this before Streamlit starts
    val = os.environ.get("BACKEND_URL", "")
    if val:
        return val

    try:
        val = st.secrets.get("BACKEND_URL", "")
        if val:
            return val
    except Exception:
        pass

    # Read from .env file (local dev)
    for env_path in [
        Path(__file__).parent.parent / ".env",
        Path(".env"),
    ]:
        if env_path.exists():
            text = _read_env_file(env_path)
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("BACKEND_URL=") and not line.startswith("#"):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val and "localhost" not in val:
                        return val

    # Default: FastAPI runs on 8000 in the same container
    return "http://localhost:8000"


for k, v in {
    "page":            "Generate",
    "last_session_id": None,
    "last_result":     None,
    "generating":      False,
    "topic_input":     "",
    "topic_field":     "",
    "safety_topic":    None,
    "safety_result":   None,
    "review_mode":     None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# api_key and backend_url: always refresh if empty so stale/crashed
# browser sessions don't get stuck with an empty key (causing 401).
# This runs every page load but _get_api_key() just reads a file — fast.
if not st.session_state.get("api_key"):
    st.session_state["api_key"] = _get_api_key()
if not st.session_state.get("backend_url"):
    st.session_state["backend_url"] = _get_backend_url()

# ── Backend status (cached — recheck every 30s, not every rerun) ──────────────
# Streamlit reruns on EVERY interaction (click, type, navigate). Checking
# /health on every rerun causes the sidebar to flicker Online/Offline on
# slow networks (like Render free tier). Caching for 30s fixes this.
import time as _time

def _check_backend_health():
    """Check backend health, cached for 30 seconds."""
    cache_key = "_backend_health_cache"
    cache_ts  = "_backend_health_ts"
    now = _time.time()

    # Return cached result if fresh (less than 30 seconds old)
    if cache_key in st.session_state and cache_ts in st.session_state:
        if now - st.session_state[cache_ts] < 30:
            return st.session_state[cache_key]

    # Fresh check
    result = {"ok": False, "data": {}}
    try:
        r = requests.get(
            f"{st.session_state.backend_url}/health",
            headers={"X-API-Key": st.session_state.get("api_key", "")},
            timeout=10,   # 10s timeout — Render free tier can be slow
        )
        if r.status_code == 200:
            result = {"ok": True, "data": r.json()}
    except Exception:
        pass

    st.session_state[cache_key] = result
    st.session_state[cache_ts]  = now
    return result

_health = _check_backend_health()
backend_ok   = _health["ok"]
backend_data = _health["data"]

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:

    # Brand header
    st.markdown("""
    <div style="padding:24px 16px 16px;margin-bottom:8px;
    border-bottom:1px solid #1a1a28">
        <div style="display:flex;align-items:center;gap:8px">
            <span style="font-size:1.1rem;color:#7c6af7">✦</span>
            <span style="font-size:0.95rem;font-weight:700;
            color:#e2e2f0;letter-spacing:0.01em">AI Content Studio</span>
        </div>
        <p style="margin:4px 0 0 0;font-size:0.68rem;color:#3a3a5a;
        text-transform:uppercase;letter-spacing:0.06em">
            Multi-Agent Generation
        </p>
    </div>
    """, unsafe_allow_html=True)

    # ── Navigation items ──────────────────────────────────────────────────────
    NAV = [
        ("◎   Generate",         "Generate"),
        ("✦   Review & Publish",  "Review"),
        ("▤   History",           "History"),
        ("◈   Observability",     "Observe"),
        ("◧   Settings",          "Settings"),
    ]

    st.markdown("<div style='padding:8px 0'>", unsafe_allow_html=True)
    for label, key in NAV:
        active = st.session_state.page == key
        if st.button(
            label,
            key=f"nav_{key}",
            use_container_width=True,
            type="primary" if active else "secondary",
        ):
            st.session_state.page = key
            # Reset review mode when switching pages
            if key != "Review":
                st.session_state["review_mode"] = None
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    st.divider()

    # ── Backend status ────────────────────────────────────────────────────────
    if backend_ok:
        st.markdown(
            "<span style='font-size:0.72rem;font-weight:600;"
            "color:#34d399'>● Online</span>",
            unsafe_allow_html=True,
        )
        st.caption(f"`{backend_data.get('model','')}`")
        chunks = backend_data.get("vector_store_chunks", 0)
        st.caption(f"RAG: {chunks} chunks")
        cache = backend_data.get("cache_stats", {})
        tc = cache.get("hits",0) + cache.get("misses",0)
        if tc > 0:
            st.caption(f"Cache: {cache.get('hit_rate_pct',0)}% hit rate")
        pub   = backend_data.get("publishing", {})
        ready = [k for k,v in pub.items() if v and k != "images"]
        if ready:
            st.caption(f"Publishers: {', '.join(ready)}")
    else:
        # Distinguish "backend still booting" (normal, ~60s after deploy)
        # from "backend genuinely down". We track when the app first loaded;
        # within the first 2 minutes, a missing backend is almost certainly
        # just the embedding model still downloading — not an error.
        if "_app_first_load_ts" not in st.session_state:
            st.session_state["_app_first_load_ts"] = _time.time()
        _uptime = _time.time() - st.session_state["_app_first_load_ts"]

        if _uptime < 120:
            st.markdown(
                "<span style='font-size:0.72rem;font-weight:600;"
                "color:#fbbf24'>● Starting up…</span>",
                unsafe_allow_html=True,
            )
            st.caption("Backend is loading the embedding model (~60s on first boot).")
            st.caption("This is normal after a deploy. Refresh in a moment.")
        else:
            st.markdown(
                "<span style='font-size:0.72rem;font-weight:600;"
                "color:#f87171'>● Offline</span>",
                unsafe_allow_html=True,
            )
            st.caption("Backend unreachable. If running locally, start it with:")
            st.caption("`uvicorn backend.main:app --port 8000`")

        if st.button("↻ Retry connection", use_container_width=True,
                     key="retry_backend_conn"):
            # Clear the 30s health cache so the next check is immediate
            st.session_state.pop("_backend_health_cache", None)
            st.session_state.pop("_backend_health_ts", None)
            st.rerun()

    # Visible diagnostic — always show a MASKED preview of the resolved key
    # so it's possible to confirm (without exposing the full secret) whether
    # the key is empty, a stale/wrong value, or the expected one.
    _k = st.session_state.get("api_key", "")
    if not _k:
        st.divider()
        st.markdown(
            "<div style='padding:8px 10px;background:#2a0f0f;"
            "border:1px solid #7f1d1d;border-radius:8px;"
            "font-size:0.7rem;color:#f87171'>"
            "⚠️ No API key loaded<br>"
            "<span style='color:#a0a0a0'>Check MASTER_API_KEY in .env, "
            "or go to Settings to set it manually.</span>"
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        _masked = (_k[:4] + "…" + _k[-4:]) if len(_k) > 10 else (_k[:2] + "…")
        st.caption(f"🔑 Key: `{_masked}` ({len(_k)} chars)")

    # Session status badge — uses cached status, no extra API calls
    _lr = st.session_state.get("last_result")
    if _lr and isinstance(_lr, dict):
        topic_short = _lr.get("topic", "")[:28]
        _status = _lr.get("hitl_status", "pending")
        _badge_map = {
            "pending":  ("⏳", "Pending review",  "#16102a", "#3d2a6e", "#a78bfa"),
            "approved": ("✅", "Approved",         "#0f2a1a", "#166534", "#4ade80"),
            "edited":   ("✏️", "Edited & Approved","#0f2a1a", "#166534", "#4ade80"),
            "rejected": ("❌", "Rejected",         "#2a0f0f", "#7f1d1d", "#f87171"),
        }
        _icon, _label, _bg, _border, _color = _badge_map.get(
            _status, ("⏳", _status, "#16102a", "#3d2a6e", "#a78bfa"))
        st.divider()
        st.markdown(
            f"<div style='padding:8px 10px;background:{_bg};"
            f"border:1px solid {_border};border-radius:8px;"
            f"font-size:0.72rem;color:{_color}'>"
            f"{_icon} {_label}<br>"
            f"<span style='font-weight:600'>{topic_short}…</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    # Footer
    st.markdown(
        "<div style='margin-top:32px;font-size:0.62rem;"
        "color:#1e1e2e;text-align:center'>"
        "LangGraph · FAISS · Groq · MCP<br>v1.0.0</div>",
        unsafe_allow_html=True,
    )

# ── Page routing — imports from ui/ ──────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

page = st.session_state.page

if page == "Generate":
    from ui import generate_page
    generate_page.show()

elif page == "Review":
    from ui import review_page
    review_page.show()

elif page == "History":
    from ui import history_page
    history_page.show()

elif page == "Observe":
    from ui import observability_page
    observability_page.show()

elif page == "Settings":
    st.markdown(
        "<h1 style='font-size:1.8rem;font-weight:700;color:#e2e2f0;"
        "margin-bottom:24px'>◧  Settings</h1>",
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Backend")
        new_url = st.text_input("URL",     value=st.session_state.backend_url)
        new_key = st.text_input("API Key", value=st.session_state.api_key,
                                 type="password")
        if st.button("Save", type="primary"):
            st.session_state.backend_url = new_url
            st.session_state.api_key     = new_key
            st.success("Saved")

    with col2:
        st.subheader("Platform Status")
        if backend_ok:
            try:
                headers = {"X-API-Key": st.session_state.api_key}
                r2 = requests.get(
                    f"{st.session_state.backend_url}/platforms/status",
                    headers=headers, timeout=5,
                )
                if r2.status_code == 200:
                    for p in r2.json().get("platforms", []):
                        ok  = "✅" if p["configured"] else "⚙️"
                        lck = " 🔒" if p.get("auto_post_restricted") else ""
                        st.markdown(
                            f"{ok} **{p['emoji']} {p['display']}**{lck}  \n"
                            f"<small style='color:#555570'>{p['message']}</small>",
                            unsafe_allow_html=True,
                        )
                        st.markdown("")
            except Exception:
                st.caption("Could not fetch platform status")

    st.divider()
    st.subheader("Deployment Note")
    st.markdown("""
    After deploying to HuggingFace Spaces, update Twitter callback URL:

    [developer.twitter.com](https://developer.twitter.com) → Your App
    → Auth Settings → Callback URLs
    → Add: `https://YOUR-HF-SPACE.hf.space/twitter/callback`

    **Stack:** LangGraph · FAISS+BM25+FlashRank · Groq Llama 3.3 70B · Tavily · MCP
    """)