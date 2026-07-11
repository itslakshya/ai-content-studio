# frontend/ui/review_page.py
import streamlit as st
import sys, os
import re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from components.api_client import (
    get_session, review_action, publish_content,
    get_platform_status, get_history, get_platform_states,
)
import requests as _requests

PLATFORM_COPY = {
    "twitter":  ("🐦", "Twitter/X",         "https://twitter.com/compose/tweet"),
    "linkedin": ("💼", "LinkedIn",           "https://linkedin.com/feed"),
    "blog":     ("📝", "Dev.to",             "https://dev.to/new"),
    "bluesky":  ("☁️", "Bluesky",            "https://bsky.app"),
    "telegram": ("✈️", "Telegram Channel",   "https://t.me"),
}
RESTRICTED = {
    "linkedin": "LinkedIn API restricts personal profile posting.",
    "twitter":  "Twitter free tier is read-only. Posting requires Basic plan ($100/mo).",
}

PLATFORM_DIMS = {
    "blog": ("1200", "630"), "linkedin": ("600", "600"),
    "bluesky": ("1200", "675"), "twitter": ("1200", "675"),
    "telegram": ("1200", "675"),
}


def _fetch_image(topic: str, session_id: str = "") -> str:
    """
    Fetch contextual image URL from the backend /preview-image endpoint.
    Passing session_id makes the image STABLE — identical to what's shown on
    the generate screen and what gets published.
    """
    try:
        base    = st.session_state.get("backend_url", "http://localhost:8000")
        headers = {"X-API-Key": st.session_state.get("api_key", "")}
        r = _requests.get(
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
    # Fallback (deterministic per session/topic)
    import hashlib
    seed = int(hashlib.md5((session_id or topic).encode()).hexdigest(), 16) % 1000
    return f"https://picsum.photos/seed/{seed}/800/420"


def _img(url: str, alt: str = "", width: str = "100%") -> str:
    """HTML img tag with graceful error handling."""
    safe_alt = alt[:30].replace('"', '').replace("'", "")
    return (
        f'<img src="{url}" alt="{safe_alt}" '
        f'style="width:{width};border-radius:10px;margin:8px 0" '
        f"onerror=\"this.style.display='none'\"/>"
    )


def _get_cached_image(topic: str, session_id: str = "") -> str:
    """
    Get image URL — cached in session state by session_id so it's stable and
    matches the generate/publish screens. Falls back to topic key if no id.
    """
    cache_key = f"_img_{session_id or topic[:30]}"
    if cache_key not in st.session_state:
        st.session_state[cache_key] = _fetch_image(topic, session_id=session_id)
    return st.session_state[cache_key]


def _render_blog_with_images(blog: str, topic: str, img_url: str) -> None:
    """Render blog replacing [IMAGE: desc] with actual images."""
    if not blog:
        return
    parts = re.split(r'\[IMAGE:([^\]]+)\]', blog)
    imgs = 0
    for i, part in enumerate(parts):
        if i % 2 == 0:
            if part.strip():
                st.markdown(part)
        else:
            if imgs < 2:
                st.markdown(_img(img_url, part.strip()[:60]), unsafe_allow_html=True)
                st.caption(f"📸 {part.strip()[:70]}")
                imgs += 1


def show():
    if st.session_state.get("review_mode") == "publish":
        _publish_view()
        return

    st.markdown("""
    <div style="margin-bottom:1.5rem">
        <div style="font-size:1.8rem;font-weight:700;letter-spacing:-0.02em;color:#e2e2f0">
            Review &amp; Publish</div>
        <div style="color:#555570;font-size:0.72rem;margin-top:3px;
        text-transform:uppercase;letter-spacing:0.05em">Approve · Edit · Publish</div>
    </div>
    """, unsafe_allow_html=True)

    col_pick, col_ref = st.columns([4, 1])
    with col_ref:
        if st.button("↻  Refresh", use_container_width=True):
            st.rerun()

    history_r = get_history()
    all_sessions = []
    if history_r["success"]:
        all_sessions = sorted(
            history_r["data"].get("sessions", []),
            key=lambda s: s.get("created_at", 0), reverse=True,
        )

    if not all_sessions:
        st.info("No sessions yet. Generate content first.")
        return

    with col_pick:
        STATUS_ICON = {"pending": "🟡", "approved": "🟢", "edited": "🟣", "rejected": "🔴"}
        opts = {}
        for s in all_sessions:
            icon = STATUS_ICON.get(s["status"], "⚪")
            age  = s.get("age_seconds", 0)
            ages = f"{int(age//60)}m" if age < 3600 else f"{int(age//3600)}h"
            opts[f"{icon}  {s['topic'][:45]}…  ({ages} ago)"] = s["session_id"]

        default = 0
        last_id = st.session_state.get("last_session_id")
        if last_id and last_id in list(opts.values()):
            default = list(opts.values()).index(last_id)

        chosen = st.selectbox("Session", list(opts.keys()),
                               index=default, label_visibility="collapsed")
        session_id = opts[chosen]

    r = get_session(session_id)
    if not r["success"]:
        st.error(f"Cannot load session: {r['error']}")
        return

    session = r["data"]
    status  = session.get("status", "pending")
    topic   = session.get("topic", "")
    sid     = session.get("session_id", "")

    # Get cached image — keyed on session_id so it matches generate/publish
    img_url = _get_cached_image(topic, session_id=sid)

    # Session header
    status_bg    = "#0f2a1a" if status in ["approved","edited"] else "#2a0f0f" if status == "rejected" else "#1a1a2a"
    status_color = "#4ade80" if status in ["approved","edited"] else "#f87171" if status == "rejected" else "#a78bfa"
    st.markdown(f"""
    <div style="padding:16px;background:#13131c;border:1px solid #1e1e2e;
    border-radius:10px;margin:14px 0">
        <div style="display:flex;align-items:flex-start;justify-content:space-between">
            <div>
                <div style="font-size:1.1rem;font-weight:600;color:#e2e2f0">{topic}</div>
                <div style="font-size:0.75rem;color:#555570;margin-top:3px">
                    {session.get('tone','').capitalize()}  ·
                    Score {session.get('critique_score',0):.2f}  ·
                    {session.get('rewrite_count',0)} rewrite(s)  ·
                    {len(session.get('sources',[]))} sources
                </div>
            </div>
            <span style="padding:4px 10px;border-radius:20px;font-size:0.7rem;font-weight:600;
            background:{status_bg};color:{status_color}">{status.upper()}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Limbo notice
    pending_others = [s for s in all_sessions
                      if s["status"] == "pending" and s["session_id"] != session_id]
    if pending_others:
        st.markdown(
            f"<div style='padding:7px 14px;background:#1a1a0f;border:1px solid #3a3a1a;"
            f"border-radius:7px;font-size:0.75rem;color:#a0a030;margin-bottom:10px'>"
            f"◎  {len(pending_others)} other session(s) pending — select from dropdown</div>",
            unsafe_allow_html=True,
        )

    # Already reviewed — show content preview with images + Publish button
    if status in ["approved", "edited", "rejected"]:
        if status == "rejected":
            st.error(f"Rejected — {session.get('reviewer_notes','')}")
        else:
            st.success(f"{'Edited & ' if status == 'edited' else ''}Approved")

        # Two actions: go to publish, OR re-open to edit again.
        if status == "rejected":
            # Rejected content: only offer re-open (nothing to publish)
            if st.button("✎  Re-open for editing", type="primary",
                         use_container_width=True):
                res = review_action(session_id, "reopen")
                if res.get("success"):
                    st.session_state["last_session_id"] = session_id
                    st.rerun()
                else:
                    st.error(res.get("error", "Failed to re-open"))
        else:
            col_pub, col_edit = st.columns([3, 2])
            with col_pub:
                if st.button("◎  Go to Publish →", type="primary",
                             use_container_width=True):
                    st.session_state["review_mode"]        = "publish"
                    st.session_state["publish_session_id"] = session_id
                    st.rerun()
            with col_edit:
                if st.button("✎  Back to editing", use_container_width=True):
                    res = review_action(session_id, "reopen")
                    if res.get("success"):
                        st.session_state["last_session_id"] = session_id
                        st.rerun()
                    else:
                        st.error(res.get("error", "Failed to re-open"))

        st.divider()
        _content_preview(session, img_url)
        return

    # ── Edit UI ───────────────────────────────────────────────────────────────
    st.info("Review content below. Edit if needed, then approve.")

    edited_tg = ""

    tab_b, tab_l, tab_t, tab_bsky, tab_tg = st.tabs([
        "Blog Post", "LinkedIn", "Twitter Thread", "Bluesky", "Telegram"
    ])

    with tab_b:
        col_p, col_e = st.columns(2)
        with col_p:
            st.caption("Preview")
            with st.container(height=400):
                # Show image in preview
                st.markdown(_img(img_url, topic, "100%"), unsafe_allow_html=True)
                _render_blog_with_images(session.get("blog_post", ""), topic, img_url)
        with col_e:
            st.caption("Edit")
            edited_blog = st.text_area(
                "blog", value=session.get("blog_post", ""),
                height=400, label_visibility="collapsed", key="eb",
            )
        wc = len(edited_blog.split())
        st.caption(f"{'🟢' if 600 <= wc <= 2500 else '🟡'} {wc} words")

    with tab_l:
        st.markdown(_img(img_url, topic, "280px"), unsafe_allow_html=True)
        edited_li = st.text_area(
            "LinkedIn", value=session.get("linkedin_post", ""),
            height=260, label_visibility="collapsed", key="eli",
        )
        st.caption(f"{'🟢' if len(edited_li) <= 1300 else '🟡'} {len(edited_li)}/1900")

    with tab_t:
        new_tweets = []
        for i, tw in enumerate(session.get("twitter_thread", []), 0):
            et = st.text_area(f"Tweet {i+1}", value=tw, height=72,
                               key=f"etw{i}", max_chars=280)
            st.caption(f"{'🟢' if len(et) <= 240 else '🟡'} {len(et)}/280")
            new_tweets.append(et)

    with tab_bsky:
        st.markdown(_img(img_url, topic, "360px"), unsafe_allow_html=True)
        bsky_val = session.get("bluesky_post", "")
        if not bsky_val:
            li_tmp = session.get("linkedin_post", "")
            bsky_val = (li_tmp[:280] + "…") if len(li_tmp) > 280 else li_tmp
        edited_bsky = st.text_area(
            "Bluesky", value=bsky_val,
            height=180, label_visibility="collapsed", key="ebsky",
            max_chars=300,
        )
        st.caption(f"{'🟢' if len(edited_bsky) <= 280 else '🟡'} {len(edited_bsky)}/300 chars")

    with tab_tg:
        st.markdown(_img(img_url, topic, "360px"), unsafe_allow_html=True)
        tg_val = session.get("telegram_post", "")
        if not tg_val:
            tg_val = (session.get("linkedin_post", "") or "")[:1020]
        edited_tg = st.text_area(
            "Telegram", value=tg_val,
            height=200, label_visibility="collapsed", key="etg",
            max_chars=1024,
        )
        st.caption(f"{'🟢' if len(edited_tg) <= 1000 else '🟡'} {len(edited_tg)}/1024 chars")
        st.caption("Sent as image caption. Supports: <b>bold</b> <i>italic</i>")

    st.divider()
    notes = st.text_input(
        "Reviewer notes",
        placeholder="e.g. Tightened LinkedIn hook",
        label_visibility="collapsed",
    )

    col_a, col_e2, col_r = st.columns(3)
    with col_a:
        if st.button("✓  Approve As-Is", type="primary", use_container_width=True):
            res = review_action(session_id, "approve", reviewer_notes=notes)
            if res["success"]:
                st.balloons()
                st.session_state["last_session_id"] = session_id
                st.rerun()
            else:
                st.error(res["error"])

    with col_e2:
        if st.button("✎  Save Edits & Approve", use_container_width=True):
            res = review_action(
                session_id, "edit",
                blog_post=edited_blog,
                linkedin_post=edited_li,
                twitter_thread=new_tweets,
                bluesky_post=edited_bsky,
                telegram_post=edited_tg,
                reviewer_notes=notes,
            )
            if res["success"]:
                st.balloons()
                st.session_state["last_session_id"] = session_id
                st.rerun()
            else:
                st.error(res["error"])

    with col_r:
        if st.button("✕  Reject", use_container_width=True):
            res = review_action(session_id, "reject",
                                reviewer_notes=notes or "No reason provided")
            if res["success"]:
                st.rerun()
            else:
                st.error(res["error"])


def _publish_view():
    """Publish screen."""
    session_id = st.session_state.get("publish_session_id") or st.session_state.get("last_session_id")
    if not session_id:
        st.session_state["review_mode"] = None
        st.rerun()
        return

    r = get_session(session_id)
    if not r["success"]:
        st.session_state["review_mode"] = None
        st.rerun()
        return

    session    = r["data"]
    topic      = session.get("topic", "")
    _sid_pub   = session.get("session_id", session_id)
    img_url    = _get_cached_image(topic, session_id=_sid_pub)

    col_b, col_title = st.columns([1, 5])
    with col_b:
        if st.button("← Back", use_container_width=True):
            st.session_state["review_mode"] = None
            st.rerun()
    with col_title:
        st.markdown(
            f'<div style="font-size:1.6rem;font-weight:700;color:#e2e2f0">Publish</div>'
            f'<div style="color:#555570;font-size:0.75rem">{topic[:60]}</div>',
            unsafe_allow_html=True,
        )

    st.divider()

    ps   = get_platform_status()
    pmap = {}
    if ps["success"]:
        for p in ps["data"].get("platforms", []):
            pmap[p["id"]] = p

    # Robustness: if status fetch failed entirely, retry once
    if not pmap:
        import time as _t
        _t.sleep(0.5)
        ps = get_platform_status()
        if ps["success"]:
            for p in ps["data"].get("platforms", []):
                pmap[p["id"]] = p

    if not pmap:
        st.warning(
            "Could not load platform status from backend. "
            "Make sure the backend server is running, then click Refresh."
        )
        if st.button("↻ Retry", use_container_width=True):
            st.rerun()

    # Fetch which platforms are ALREADY published for this session so we don't
    # show a Publish checkbox for them (prevents accidental double-posting).
    already_published = {}
    _states_resp = get_platform_states(session_id)
    if _states_resp.get("success"):
        for _pid, _info in _states_resp["data"].get("states", {}).items():
            if _info.get("state") == "published":
                already_published[_pid] = _info.get("url", "")

    tab_auto, tab_copy = st.tabs(["Auto-Publish", "Copy & Paste"])

    with tab_auto:
        st.markdown(
            "<p style='font-size:0.75rem;color:#6c6c8a;margin-bottom:10px'>Select platforms:</p>",
            unsafe_allow_html=True,
        )

        selected = []
        platform_order = ["blog", "bluesky", "telegram", "twitter", "linkedin"]
        cols = st.columns(5)

        for i, pid in enumerate(platform_order):
            p_info     = pmap.get(pid, {})
            configured = p_info.get("configured", False)
            restricted = pid in RESTRICTED
            is_published = pid in already_published
            emoji, display, _ = PLATFORM_COPY.get(pid, ("·", pid, ""))

            with cols[i]:
                st.markdown(
                    f"<p style='font-size:0.8rem;font-weight:600;color:#e2e2f0;margin:0 0 4px'>"
                    f"{emoji} {display}</p>", unsafe_allow_html=True,
                )
                if is_published:
                    # Already posted — no checkbox, show a View link instead
                    _purl = already_published.get(pid, "")
                    st.markdown("<small style='color:#4ade80'>✅ Published</small>",
                                unsafe_allow_html=True)
                    if _purl and _purl.startswith("http"):
                        st.markdown(
                            f"<small><a href='{_purl}' target='_blank' "
                            f"style='color:#22c55e'>View ↗</a></small>",
                            unsafe_allow_html=True,
                        )
                elif restricted:
                    st.markdown("<small style='color:#3a3a5a'>🔒 Restricted</small>",
                                unsafe_allow_html=True)
                    st.checkbox(display, value=False, disabled=True, key=f"ap_{pid}")
                elif configured:
                    if st.checkbox(display, value=True, key=f"ap_{pid}"):
                        selected.append(pid)
                    st.markdown("<small style='color:#34d399'>● Ready</small>",
                                unsafe_allow_html=True)
                else:
                    st.checkbox(display, value=False, disabled=True, key=f"ap_{pid}_nc")
                    st.markdown(
                        f"<small style='color:#555570'>{p_info.get('message','Not configured')[:25]}</small>",
                        unsafe_allow_html=True,
                    )

        for pid, msg in RESTRICTED.items():
            if pmap.get(pid, {}).get("configured"):
                emoji, display, _ = PLATFORM_COPY.get(pid, ("·", pid, ""))
                st.markdown(
                    f"<div style='margin:6px 0;padding:7px 12px;background:#1a1420;"
                    f"border-radius:6px;font-size:0.73rem;color:#8a7ab0'>"
                    f"{emoji} <strong>{display}:</strong> {msg} Use Copy &amp; Paste.</div>",
                    unsafe_allow_html=True,
                )

        gen_img = st.checkbox("Generate contextual images (Pexels)", value=True)

        if selected:
            if st.button("Publish →", type="primary", use_container_width=True):
                with st.spinner("Publishing…"):
                    res = publish_content(session_id, selected, gen_img)

                if res["success"]:
                    pub  = res["data"]["publishing_results"]
                    imgs = pub.get("images", {})
                    st.markdown(
                        "<p style='font-weight:600;color:#34d399;margin:12px 0 8px'>Published</p>",
                        unsafe_allow_html=True,
                    )
                    for pid in selected:
                        pr      = pub.get(pid, {})
                        emoji, display, _ = PLATFORM_COPY.get(pid, ("·", pid, ""))
                        img_url_pub = imgs.get(pid, "")
                        if pr.get("success"):
                            url = pr.get("url", "")
                            st.markdown(
                                f"✅ **{emoji} {display}**"
                                + (f" — [View post ↗]({url})" if url else ""),
                            )
                            if img_url_pub and isinstance(img_url_pub, str) and img_url_pub.startswith("http"):
                                st.markdown(
                                    f'<img src="{img_url_pub}" alt="{display}" '
                                    f'style="width:280px;border-radius:6px;margin:6px 0" '
                                    f"onerror=\"this.style.display='none'\"/>",
                                    unsafe_allow_html=True,
                                )
                        else:
                            err = pr.get("error", "Failed")
                            if "402" in err or "credits" in err.lower():
                                st.warning(f"⚠️ **{emoji} {display}**: Requires paid API. Use Copy & Paste.")
                            elif "already been used" in err.lower() or "422" in err:
                                st.warning(f"⚠️ **{emoji} {display}**: Title used recently — retried with date.")
                            else:
                                st.error(f"❌ **{emoji} {display}**: {err[:120]}")

                    # Refresh so published platforms now show as ✅ Published
                    # and can't be accidentally posted again.
                    st.caption("Refresh to update platform status:")
                    if st.button("↻ Refresh status", use_container_width=True,
                                 key="post_publish_refresh"):
                        st.rerun()
                else:
                    st.error(f"Error: {res['error']}")
        else:
            st.markdown(
                "<p style='color:#555570;font-size:0.82rem'>No platforms selected or configured.</p>",
                unsafe_allow_html=True,
            )

    with tab_copy:
        st.markdown(
            "<p style='font-size:0.75rem;color:#6c6c8a;margin-bottom:14px'>"
            "Copy content for each platform:</p>", unsafe_allow_html=True,
        )
        blog   = session.get("blog_post", "")
        li     = session.get("linkedin_post", "")
        tweets = session.get("twitter_thread", [])
        tw_fmt = "\n\n".join([f"{i}/ {t}" for i, t in enumerate(tweets, 1)])
        bsky   = session.get("bluesky_post", "") or ((li[:280] + "…") if len(li) > 280 else li)
        tg     = session.get("telegram_post", "") or (bsky[:1020] if bsky else "")

        copy_map = {
            "blog":     ("📝", "Dev.to Blog",      blog,    "https://dev.to/new",
                         "Paste in editor — cover image attached automatically"),
            "linkedin": ("💼", "LinkedIn",          li,      "https://linkedin.com/feed",
                         "Start a post → paste → add image"),
            "twitter":  ("🐦", "Twitter / X",       tw_fmt,  "https://twitter.com/compose/tweet",
                         "Post tweet 1 → reply with 2, 3… to form thread"),
            "bluesky":  ("☁️", "Bluesky",           bsky,    "https://bsky.app",
                         "New Post → paste (300 char limit)"),
            "telegram": ("✈️", "Telegram Channel",  tg,      "https://t.me",
                         "Auto-publish or paste in channel"),
        }

        st.caption(
            "Each platform shows the content RENDERED as it will look. "
            "Expand “Copy raw text” under any platform to copy it."
        )

        for pid, (emoji, display, val, url, tip) in copy_map.items():
            if not val:
                continue
            with st.expander(f"{emoji}  {display}", expanded=False):
                if pid == "twitter":
                    # Rendered view: each tweet as it will appear
                    for i2, tw in enumerate(tweets, 1):
                        st.markdown(
                            f"<div style='background:#13131c;border:1px solid #1e1e2e;"
                            f"border-radius:10px;padding:12px;margin-bottom:8px'>"
                            f"<div style='color:#888;font-size:0.7rem;margin-bottom:4px'>"
                            f"Tweet {i2}/{len(tweets)} · {len(tw)}/280</div>"
                            f"<div style='color:#e2e2f0'>{tw}</div></div>",
                            unsafe_allow_html=True,
                        )
                    with st.expander("📋 Copy raw text (whole thread)", expanded=False):
                        st.code(tw_fmt, language=None)
                        st.caption("Or copy tweets individually:")
                        for i2, tw in enumerate(tweets, 1):
                            st.code(tw, language=None)

                elif pid == "blog":
                    # Render the blog EXACTLY like the preview (bold, headings,
                    # images replacing [IMAGE:] markers).
                    st.markdown(_img(img_url, topic, "100%"), unsafe_allow_html=True)
                    _render_blog_with_images(val, topic, img_url)
                    with st.expander("📋 Copy raw text (Markdown)", expanded=False):
                        st.caption("Dev.to renders this Markdown automatically:")
                        st.code(val, language="markdown")

                else:
                    # LinkedIn / Bluesky / Telegram: render the text as it appears.
                    # Convert **bold**/<b> to proper formatting for display.
                    _rendered = val
                    st.markdown(
                        f"<div style='background:#13131c;border:1px solid #1e1e2e;"
                        f"border-radius:10px;padding:14px;color:#e2e2f0;"
                        f"white-space:pre-wrap'>{_rendered}</div>",
                        unsafe_allow_html=True,
                    )
                    with st.expander("📋 Copy raw text", expanded=False):
                        st.code(val, language=None)

                st.markdown(f"👉 **[Open {display} ↗]({url})**")
                st.caption(f"💡 {tip}")


def _content_preview(session: dict, img_url: str):
    """Read-only content preview with images."""
    topic = session.get("topic", "")

    st.markdown(
        "<p style='font-size:0.72rem;color:#555570;margin:18px 0 10px;"
        "text-transform:uppercase;letter-spacing:0.05em'>Content</p>",
        unsafe_allow_html=True,
    )

    tb, tl, tt, tbsky, ttg = st.tabs(["Blog", "LinkedIn", "Twitter", "Bluesky", "Telegram"])

    with tb:
        st.markdown(_img(img_url, topic, "100%"), unsafe_allow_html=True)
        st.caption("Cover image")
        _render_blog_with_images(session.get("blog_post", ""), topic, img_url)

    with tl:
        st.markdown(_img(img_url, topic, "280px"), unsafe_allow_html=True)
        st.markdown(
            f"<div class='content-block'>{session.get('linkedin_post','')}</div>",
            unsafe_allow_html=True,
        )

    with tt:
        for i, tw in enumerate(session.get("twitter_thread", []), 1):
            st.markdown(f"**{i}.** {tw}")
            st.caption(f"{len(tw)}/280")

    with tbsky:
        bsky = session.get("bluesky_post", "")
        if not bsky:
            li = session.get("linkedin_post", "")
            bsky = (li[:280] + "…") if len(li) > 280 else li
        st.markdown(_img(img_url, topic, "360px"), unsafe_allow_html=True)
        st.markdown(f"<div class='content-block'>{bsky}</div>", unsafe_allow_html=True)
        st.caption(f"{len(bsky)}/300 chars")

    with ttg:
        tg = session.get("telegram_post", "")
        if not tg:
            tg = (session.get("linkedin_post", "") or "")[:1020]
        st.markdown(_img(img_url, topic, "360px"), unsafe_allow_html=True)
        st.markdown(f"<div class='content-block'>{tg}</div>", unsafe_allow_html=True)
        st.caption(f"{len(tg)}/1024 chars — Telegram channel caption")