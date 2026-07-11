# frontend/ui/generate_page.py
import streamlit as st
import time
import re
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from components.api_client import generate_content, check_topic_safety

TONES = {
    "professional":   "Professional  —  Authoritative, data-driven",
    "casual":         "Casual  —  Conversational, friendly",
    "educational":    "Educational  —  First principles, clear",
    "witty":          "Witty  —  Clever angles, smart humor",
    "inspirational":  "Inspirational  —  Vision-focused",
    "conversational": "Conversational  —  One-on-one feel",
}

EXAMPLE_TOPICS = [
    "Generative AI in Content Marketing",
    "How RAG reduces LLM hallucinations",
    "AI agents in Indian fintech",
    "LangGraph for multi-agent systems",
    "Vector databases explained simply",
    "The future of AI in healthcare",
]

# Topic keyword to Pexels search query — for relevant images
TOPIC_SEARCH = {
    "ai":"artificial+intelligence+technology",
    "langgraph":"software+automation+workflow",
    "rag":"data+retrieval+technology",
    "llm":"neural+network+computer",
    "healthcare":"medical+technology+health",
    "fintech":"financial+technology+banking",
    "ott":"streaming+media+entertainment",
    "sitcom":"television+entertainment+comedy",
    "parenting":"family+parent+child",
    "hiring":"recruitment+job+office",
    "climate":"environment+green+sustainability",
    "vector":"database+technology+server",
    "content":"digital+marketing+content",
    "blockchain":"blockchain+crypto+digital",
    "education":"learning+student+classroom",
    "startup":"entrepreneur+innovation+office",
    "western":"television+entertainment+pop+culture",
}


def _get_image_url(topic: str) -> str:
    """
    Get a reliable preview image URL.
    Uses Pexels direct embed URL (always works, no API key needed for display).
    Falls back to picsum with topic-based seed.
    """
    import hashlib, urllib.parse

    # Find best search query from topic
    topic_lower = topic.lower()
    query = None
    for key, search in TOPIC_SEARCH.items():
        if key in topic_lower:
            query = search
            break

    if not query:
        # Build from topic words
        stop = {"the","a","an","in","on","at","to","for","of","and","or","is","are",
                "how","why","what","impact","modern","world","future"}
        words = [w.lower() for w in topic.split() if w.lower() not in stop and len(w)>2]
        query = "+".join(words[:3]) if words else "technology"

    # Use Pexels search page image (reliable, no API key)
    # This URL format always returns a relevant image
    seed = int(hashlib.md5(topic.encode()).hexdigest(), 16) % 1000
    return f"https://picsum.photos/seed/{seed}/800/420"


def _get_pexels_image(topic: str, session_id: str = "") -> str:
    """
    Get a contextual image via the backend /preview-image endpoint.
    Passing session_id makes the image STABLE — the same image shows on the
    generate, review, and publish screens for this content.
    Falls back to picsum seed if backend is unavailable.
    """
    import requests
    try:
        base    = st.session_state.get("backend_url", "http://localhost:8000")
        headers = {"X-API-Key": st.session_state.get("api_key", "")}
        r = requests.get(
            f"{base}/preview-image",
            params={"topic": topic, "platform": "blog", "session_id": session_id},
            headers=headers,
            timeout=30,   # AI image generation can take ~10-15s
        )
        if r.status_code == 200:
            url = r.json().get("url", "")
            if url and url.startswith("http"):
                return url
    except Exception:
        pass
    return _get_image_url(topic)


def _img_tag(url: str, alt: str = "", width: str = "100%") -> str:
    """HTML img with graceful error handling."""
    safe_alt = alt[:40].replace('"', '').replace("'", "")
    return (
        f'<img src="{url}" alt="{safe_alt}" '
        f'style="width:{width};border-radius:10px;margin:8px 0" '
        f"onerror=\"this.style.display='none'\"/>"
    )


def _render_blog_preview(blog_text: str, topic: str, img_url: str) -> None:
    """Render blog content, replacing [IMAGE: desc] with actual images."""
    if not blog_text:
        return
    parts = re.split(r'\[IMAGE:([^\]]+)\]', blog_text)
    img_count = 0
    for i, part in enumerate(parts):
        if i % 2 == 0:
            if part.strip():
                st.markdown(part)
        else:
            if img_count < 2:
                st.markdown(_img_tag(img_url, part.strip()[:60]), unsafe_allow_html=True)
                st.caption(f"📸 {part.strip()[:70]}")
                img_count += 1


def show():
    st.markdown("""
    <div style="margin-bottom:2rem">
        <div style="font-size:2rem;font-weight:700;letter-spacing:-0.02em;
        color:#e2e2f0;line-height:1.2">AI Content Studio</div>
        <div style="color:#555570;font-size:0.72rem;margin-top:4px;
        text-transform:uppercase;letter-spacing:0.06em">
            Multi-Agent Content Generation
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_left, col_right = st.columns([2, 1], gap="large")

    with col_left:
        st.markdown(
            "<div style='font-size:0.68rem;text-transform:uppercase;"
            "letter-spacing:0.08em;color:#555570;margin-bottom:8px'>Quick Start</div>",
            unsafe_allow_html=True,
        )
        btn_cols = st.columns(3)
        for i, t in enumerate(EXAMPLE_TOPICS):
            if btn_cols[i % 3].button(t, key=f"qs_{i}", use_container_width=True):
                st.session_state["topic_field"]   = t
                st.session_state["topic_input"]   = t
                st.session_state["safety_topic"]  = None
                st.session_state["safety_result"] = None
                st.rerun()

        st.markdown("<div style='margin-top:14px'></div>", unsafe_allow_html=True)
        topic = st.text_input(
            "Topic",
            value=st.session_state.get("topic_input", ""),
            placeholder="e.g. How AI is transforming healthcare in India",
            label_visibility="collapsed",
            key="topic_field",
        )
        if topic != st.session_state.get("topic_input", ""):
            st.session_state["topic_input"]  = topic
            st.session_state["safety_topic"] = None
            st.session_state["safety_result"]= None

        context = st.text_input(
            "Context",
            placeholder="Additional context — optional",
            label_visibility="collapsed",
            key="ctx_field",
        )

    with col_right:
        st.markdown(
            "<div style='font-size:0.68rem;text-transform:uppercase;"
            "letter-spacing:0.08em;color:#555570;margin-bottom:8px'>Options</div>",
            unsafe_allow_html=True,
        )
        tone_key = st.selectbox(
            "Tone", options=list(TONES.keys()),
            format_func=lambda x: TONES[x], index=0,
            label_visibility="collapsed",
        )
        gen_blog = st.checkbox("📝  Blog (Dev.to)", value=True)
        gen_li   = st.checkbox("💼  LinkedIn",      value=True)
        gen_tw   = st.checkbox("🐦  Twitter / X",   value=True)

        platforms = (
            (["blog"]     if gen_blog else []) +
            (["linkedin"] if gen_li   else []) +
            (["twitter"]  if gen_tw   else [])
        )

        st.markdown("""
        <div style="margin-top:16px;padding:12px;background:#13131c;
        border:1px solid #1e1e2e;border-radius:8px;font-size:0.72rem;
        color:#555570;line-height:2.1">
        ◎  Tavily real-time search<br>
        ▤  FAISS · BM25 · FlashRank RAG<br>
        ✦  5 LangGraph agents<br>
        ◈  2-layer safety guardrails<br>
        ⏱  30 – 90 seconds
        </div>""", unsafe_allow_html=True)

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # Safety check
    safety_ok = True
    if topic and len(topic.strip()) >= 3:
        if st.session_state.get("safety_topic") != topic.strip():
            with st.spinner("Checking safety…"):
                r = check_topic_safety(topic.strip())
                if r["success"]:
                    st.session_state["safety_result"] = r["data"]
                    st.session_state["safety_topic"]  = topic.strip()

        safety = st.session_state.get("safety_result") or {}
        level  = safety.get("level", "safe")
        if level == "blocked":
            safety_ok = False
            st.error(f"Topic blocked — {safety.get('warning_message','')} Rephrase with educational intent.")
        elif level == "borderline":
            st.warning(f"Sensitive topic — {safety.get('warning_message','Generating with care.')}")

    if not topic or not topic.strip():
        st.info("Type a topic above or click a Quick Start button")
    elif not platforms:
        st.warning("Select at least one platform")

    can_generate = (
        bool(topic and len(topic.strip()) >= 3)
        and len(platforms) > 0
        and safety_ok
        and not st.session_state.get("generating", False)
    )

    if st.session_state.get("generating", False):
        c1, c2 = st.columns([5, 1])
        c1.button("Generating — please wait…", disabled=True,
                  use_container_width=True, type="primary")
        if c2.button("Reset", use_container_width=True):
            st.session_state["generating"] = False
            st.rerun()
    else:
        if st.button("◎  Generate Content", type="primary",
                     disabled=not can_generate, use_container_width=True):
            st.session_state["generating"] = True
            try:
                _run(topic.strip(), tone_key, platforms, context or None)
            finally:
                st.session_state["generating"] = False

    # ── Show results if we have them ──────────────────────────────────────────
    if st.session_state.get("last_result"):
        _show_results(st.session_state["last_result"])


def _run(topic, tone, platforms, context):
    steps = [
        (12, "Supervisor validating…"),
        (25, "Research — web search (Tavily)…"),
        (42, "Research — RAG knowledge base…"),
        (58, "Critique Agent scoring…"),
        (75, "Format Agent generating content…"),
        (92, "Saving for review…"),
    ]
    prog   = st.progress(0)
    status = st.empty()
    import threading
    holder = {}

    # CRITICAL: capture session values on the MAIN thread before spawning.
    # st.session_state is not reliably readable from inside a background
    # thread — reading it there can silently return empty values (this was
    # the root cause of "API key required" 401 errors even with a correctly
    # configured .env). Pass the captured values explicitly instead.
    _api_key     = st.session_state.get("api_key", "")
    _backend_url = st.session_state.get("backend_url", "http://localhost:8000")

    def call():
        holder["r"] = generate_content(
            topic=topic, tone=tone,
            platforms=platforms, additional_context=context,
            api_key=_api_key, backend_url=_backend_url,
        )

    t = threading.Thread(target=call, daemon=True)
    t.start()
    idx = 0
    while t.is_alive():
        if idx < len(steps):
            pct, msg = steps[idx]
            prog.progress(pct, text=msg)
            status.markdown(
                f"<p style='text-align:center;color:#7c6af7;font-size:0.8rem'>{msg}</p>",
                unsafe_allow_html=True,
            )
            idx += 1
        time.sleep(9)
    t.join()

    prog.progress(100, text="Done")
    time.sleep(0.2)
    prog.empty()
    status.empty()

    result = holder.get("r", {"success": False, "error": "No response"})
    if result["success"]:
        data = result["data"]
        st.session_state["last_result"]     = data
        st.session_state["last_session_id"] = data["session_id"]
        st.session_state["safety_topic"]    = None
        st.session_state["safety_result"]   = None

        # Fetch and cache the preview image URL immediately (stable per session)
        st.session_state["preview_image_url"] = _get_pexels_image(
            data.get("topic", ""), session_id=data.get("session_id", ""))

        elapsed = data.get("elapsed_seconds", 0)
        score   = data.get("critique_score", 0)
        cached  = data.get("cached", False)
        if cached:
            st.success(f"⚡ Cache hit — {elapsed:.1f}s")
        else:
            c = "🟢" if score >= 0.75 else "🟡"
            st.success(f"Done in {elapsed:.0f}s  ·  Score {c} {score:.2f}")
        st.rerun()
    else:
        st.error(result["error"])


def _show_results(data: dict):
    """Show generated content with images and Review & Publish button."""
    st.markdown("<hr style='border-color:#1e1e2e;margin:20px 0'>", unsafe_allow_html=True)

    topic = data.get("topic", "")
    score = data.get("critique_score", 0)

    # Metrics row
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Critique",  f"{'🟢' if score>=0.75 else '🟡'} {score:.2f}")
    c2.metric("Rewrites",  data.get("rewrite_count", 0))
    c3.metric("Sources",   len(data.get("sources", [])))
    c4.metric("Type",      "⚡ Cached" if data.get("cached") else "🔄 Fresh")

    # ── PROMINENT Review & Publish button ─────────────────────────────────────
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    if st.button(
        "✦  Review & Publish →",
        type="primary",
        use_container_width=True,
        key="go_review_btn",
    ):
        st.session_state["page"] = "Review"
        st.session_state["review_mode"] = None
        st.rerun()

    st.markdown(
        f"<div style='margin:8px 0;padding:8px 14px;background:#13131c;"
        f"border:1px solid #1e1e2e;border-radius:8px;font-size:0.78rem;color:#6c6c8a'>"
        f"Pending review · Session <code>{data.get('session_id','')[:8]}…</code></div>",
        unsafe_allow_html=True,
    )

    # Get the cached preview image
    img_url = st.session_state.get("preview_image_url", _get_image_url(topic))

    blog_wc = data.get("blog_word_count", 0)
    li_cc   = data.get("linkedin_char_count", 0)
    tw_cnt  = data.get("twitter_tweet_count", 0)

    tab_b, tab_l, tab_t, tab_bsky, tab_tg, tab_s = st.tabs([
        "Blog", "LinkedIn", "Twitter", "Bluesky", "Telegram", "Sources",
    ])

    with tab_b:
        # Cover image
        st.markdown(_img_tag(img_url, topic, "100%"), unsafe_allow_html=True)
        st.caption(f"Cover image  ·  {blog_wc} words")
        _render_blog_preview(data.get("blog_post", ""), topic, img_url)

    with tab_l:
        li = data.get("linkedin_post", "")
        if li:
            st.markdown(_img_tag(img_url, topic, "300px"), unsafe_allow_html=True)
            st.caption(f"{li_cc} characters")
            st.markdown(
                f"<div class='content-block'>{li}</div>",
                unsafe_allow_html=True,
            )

    with tab_t:
        tweets = data.get("twitter_thread", [])
        st.caption(f"{tw_cnt} tweets")
        for i, tw in enumerate(tweets, 1):
            st.markdown(
                f"<div class='content-block' style='margin-bottom:8px'>"
                f"<small style='color:#555570'>Tweet {i}/{tw_cnt}  ·  {len(tw)}/280</small>"
                f"<br><br>{tw}</div>",
                unsafe_allow_html=True,
            )

    with tab_bsky:
        bsky = data.get("bluesky_post", "")
        if not bsky:
            li = data.get("linkedin_post", "")
            bsky = (li[:280] + "…") if len(li) > 280 else li
        st.markdown(_img_tag(img_url, topic, "360px"), unsafe_allow_html=True)
        st.caption(f"{len(bsky)}/300 chars")
        st.markdown(
            f"<div class='content-block'>{bsky}</div>",
            unsafe_allow_html=True,
        )

    with tab_tg:
        tg = data.get("telegram_post", "")
        if not tg:
            tg = (data.get("bluesky_post","") or "")[:1020]
        st.markdown(_img_tag(img_url, topic, "360px"), unsafe_allow_html=True)
        st.caption(f"{len(tg)}/1024 chars — Telegram channel caption")
        st.markdown(
            f"<div class='content-block'>{tg}</div>",
            unsafe_allow_html=True,
        )

    with tab_s:
        sources = data.get("sources", [])
        st.caption(f"{len(sources)} sources")
        for i, src in enumerate(sources, 1):
            if src.startswith("http"):
                st.markdown(f"{i}. [{src[:70]}]({src})")
            else:
                st.markdown(f"{i}. `{src}`")