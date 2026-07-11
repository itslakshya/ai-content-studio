# frontend/ui/history_page.py
import streamlit as st
import sys, os
import requests as _req
import re as _re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from components.api_client import get_history, review_action, reject_platform, get_platform_states

PLATFORM_META = {
    "twitter":  ("🐦", "Twitter/X"),
    "linkedin": ("💼", "LinkedIn"),
    "blog":     ("📝", "Dev.to"),
    "bluesky":  ("☁️", "Bluesky"),
    "telegram": ("✈️", "Telegram"),
}

ALL_PLATFORMS = ["blog", "bluesky", "telegram", "twitter", "linkedin"]


def _get_image(topic: str, session_id: str = "") -> str:
    """
    Fetch contextual image — cached per session_id so it's STABLE and matches
    the generate/review/publish screens for the same content.
    """
    cache_key = f"_hist_img_{session_id or topic[:30]}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]
    try:
        base    = st.session_state.get("backend_url", "http://localhost:8000")
        headers = {"X-API-Key": st.session_state.get("api_key", "")}
        r = _req.get(f"{base}/preview-image",
                     params={"topic": topic, "platform": "blog", "session_id": session_id},
                     headers=headers, timeout=30)   # AI gen can take ~10-15s
        if r.status_code == 200:
            url = r.json().get("url", "")
            if url and url.startswith("http"):
                st.session_state[cache_key] = url
                return url
    except Exception:
        pass
    import hashlib
    seed = int(hashlib.md5((session_id or topic).encode()).hexdigest(), 16) % 1000
    url  = f"https://picsum.photos/seed/{seed}/800/400"
    st.session_state[cache_key] = url
    return url


def _img(url: str, alt: str = "", width: str = "100%") -> str:
    safe = alt[:30].replace('"', '').replace("'", "")
    return (
        f'<img src="{url}" alt="{safe}" '
        f'style="width:{width};border-radius:8px;margin:6px 0" '
        f"onerror=\"this.style.display='none'\"/>\n"
    )


def _render_blog(blog: str, img_url: str) -> None:
    """Render blog preview with inline images."""
    parts = _re.split(r'\[IMAGE:([^\]]+)\]', blog)
    imgs  = 0
    for i, part in enumerate(parts):
        if i % 2 == 0:
            if part.strip():
                lines = part.split("\n")
                st.markdown("\n".join(lines[:12]))
                if len(lines) > 12:
                    st.caption(f"… {len(lines)-12} more lines")
        else:
            if imgs < 1:
                st.markdown(_img(img_url, part.strip()[:60]), unsafe_allow_html=True)
                imgs += 1


def _platform_publish_status(session: dict) -> dict:
    """
    Returns per-platform status by querying the backend for the authoritative
    state (published / rejected / unpublished) from the publishes table.

    state: "published" | "unpublished" | "rejected"
    """
    sid = session.get("session_id", "")
    result = {pid: {"state": "unpublished", "url": ""} for pid in ALL_PLATFORMS}

    # Fetch real per-platform states from backend (includes rejections)
    states_resp = get_platform_states(sid)
    if states_resp.get("success"):
        backend_states = states_resp["data"].get("states", {})
        for pid, info in backend_states.items():
            if pid in result:
                st_val = info.get("state", "unpublished")
                url    = info.get("url", "")
                if url.startswith("published:") or url.startswith("rejected:"):
                    url = ""
                result[pid] = {"state": st_val, "url": url}

    return result


def show():
    st.markdown("""
    <div style="margin-bottom:1.5rem">
        <div style="font-size:1.8rem;font-weight:700;letter-spacing:-0.02em;color:#e2e2f0">
            History</div>
        <div style="color:#555570;font-size:0.72rem;margin-top:3px;
        text-transform:uppercase;letter-spacing:0.05em">All sessions &amp; platform status</div>
    </div>
    """, unsafe_allow_html=True)

    col_t, col_r = st.columns([4, 1])
    with col_r:
        if st.button("↻  Refresh", use_container_width=True):
            st.rerun()

    result = get_history()
    if not result["success"]:
        st.error(f"Failed to load: {result['error']}")
        return

    data     = result["data"]
    sessions = data.get("sessions", [])
    cache    = data.get("cache_stats", {})

    # Cache stats
    if cache:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Cache Hits",   cache.get("hits", 0))
        c2.metric("Cache Misses", cache.get("misses", 0))
        c3.metric("Hit Rate",     f"{cache.get('hit_rate_pct',0)}%")
        c4.metric("Cached",       f"{cache.get('cache_size',0)}/{cache.get('max_size',100)}")
        st.divider()

    if not sessions:
        st.info("No sessions yet.")
        return

    # Summary
    approved = sum(1 for s in sessions if s["status"] in ["approved","edited"])
    pending  = sum(1 for s in sessions if s["status"] == "pending")
    rejected = sum(1 for s in sessions if s["status"] == "rejected")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total",    len(sessions))
    c2.metric("Approved", approved)
    c3.metric("Pending",  pending)
    c4.metric("Rejected", rejected)

    if pending > 0:
        st.markdown(
            f"<div style='margin:10px 0;padding:8px 14px;background:#1a1a0f;"
            f"border:1px solid #3a3a1a;border-radius:7px;font-size:0.75rem;color:#a0a030'>"
            f"◎  {pending} session(s) pending review</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # Filter
    col_f, _ = st.columns(2)
    with col_f:
        sf = st.multiselect(
            "Filter by status",
            ["pending","approved","edited","rejected"],
            default=["pending","approved","edited","rejected"],
            label_visibility="collapsed",
        )

    sessions_sorted = sorted(sessions, key=lambda x: x.get("created_at",0), reverse=True)
    filtered = [s for s in sessions_sorted if s["status"] in sf]
    st.caption(f"{len(filtered)} of {len(sessions)} sessions")

    STATUS_COLOR = {
        "pending":  ("#1a1a2a","#a78bfa"),
        "approved": ("#0f2a1a","#4ade80"),
        "edited":   ("#1a0f2a","#c084fc"),
        "rejected": ("#2a0f0f","#f87171"),
    }

    for s in filtered:
        status  = s.get("status","pending")
        score   = s.get("critique_score",0)
        topic   = s.get("topic","")
        age     = s.get("age_seconds",0)
        age_str = f"{int(age//60)}m" if age < 3600 else f"{int(age//3600)}h"
        sid     = s.get("session_id","")
        bg, fg  = STATUS_COLOR.get(status, ("#1a1a2a","#a78bfa"))

        # Get per-platform status
        pstatus = _platform_publish_status(s)
        n_published   = sum(1 for v in pstatus.values() if v["state"] == "published")
        n_unpublished = sum(1 for v in pstatus.values() if v["state"] == "unpublished")
        n_total       = len(ALL_PLATFORMS)

        # Build expander label
        pub_badge = ""
        if n_published == n_total:
            pub_badge = " · ✅ All published"
        elif n_published > 0:
            pub_badge = f" · ✅ {n_published}/{n_total} published"

        with st.expander(
            f"{topic[:50]}  —  {status.upper()}{pub_badge}  ·  {age_str} ago",
            expanded=False,
        ):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Score",    f"{score:.2f}")
            c2.metric("Rewrites", s.get("rewrite_count",0))
            c3.metric("Tone",     s.get("tone","N/A").capitalize())
            c4.metric("Sources",  len(s.get("sources",[])))

            # ── Per-platform publish status ────────────────────────────────────
            st.markdown(
                "<p style='font-size:0.7rem;text-transform:uppercase;letter-spacing:0.05em;"
                "color:#555570;margin:10px 0 6px'>Platform Status</p>",
                unsafe_allow_html=True,
            )

            # Platform grid — Streamlit columns so each unpublished platform
            # can have its OWN reject button (per-platform action, not bulk)
            pcols = st.columns(len(ALL_PLATFORMS))
            for ci, pid in enumerate(ALL_PLATFORMS):
                emoji, name = PLATFORM_META.get(pid, ("·", pid))
                pinfo  = pstatus.get(pid, {})
                pstate = pinfo.get("state", "unpublished")
                purl   = pinfo.get("url", "")

                with pcols[ci]:
                    if pstate == "published":
                        st.markdown(
                            f"<div style='text-align:center;padding:8px 4px;min-height:64px;"
                            f"background:#0f2a1a;border:1px solid #166534;border-radius:8px'>"
                            f"<div style='font-size:1.1rem'>{emoji}</div>"
                            f"<div style='color:#4ade80;font-size:0.6rem'>✅ Published</div>"
                            + (f"<a href='{purl}' target='_blank' style='color:#22c55e;font-size:0.58rem'>View ↗</a>" if purl else "")
                            + "</div>",
                            unsafe_allow_html=True,
                        )
                    elif pstate == "rejected":
                        st.markdown(
                            f"<div style='text-align:center;padding:8px 4px;min-height:64px;"
                            f"background:#2a0f0f;border:1px solid #7f1d1d;border-radius:8px'>"
                            f"<div style='font-size:1.1rem'>{emoji}</div>"
                            f"<div style='color:#f87171;font-size:0.6rem'>✕ Rejected</div></div>",
                            unsafe_allow_html=True,
                        )
                    else:
                        # Unpublished — show platform + a small reject button for THIS platform
                        st.markdown(
                            f"<div style='text-align:center;padding:6px 4px 2px;min-height:42px;"
                            f"background:#13131c;border:1px solid #2a2a3e;border-radius:8px 8px 0 0'>"
                            f"<div style='font-size:1.1rem'>{emoji}</div>"
                            f"<div style='color:#555570;font-size:0.58rem'>○ Pending</div></div>",
                            unsafe_allow_html=True,
                        )
                        if st.button("✕ Reject", key=f"rejp_{sid[:8]}_{pid}",
                                     use_container_width=True):
                            res = reject_platform(sid, pid)
                            if res.get("success"):
                                st.rerun()
                            else:
                                st.error(res.get("error", "Failed"))

                        # ── Content tabs ──────────────────────────────────────────────────
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            _img_url = _get_image(topic, session_id=sid)

            tb, tl, tt, tbsky, ttg = st.tabs(["Blog","LinkedIn","Twitter","Bluesky","Telegram"])

            with tb:
                blog = s.get("blog_post","")
                st.markdown(_img(_img_url, topic, "100%"), unsafe_allow_html=True)
                st.caption("Cover image")
                _render_blog(blog, _img_url)

            with tl:
                li = s.get("linkedin_post","")
                st.markdown(_img(_img_url, topic, "240px"), unsafe_allow_html=True)
                st.markdown(
                    f"<div class='content-block' style='font-size:0.8rem'>"
                    f"{li[:400]}{'…' if len(li)>400 else ''}</div>",
                    unsafe_allow_html=True,
                )

            with tt:
                for i, tw in enumerate(s.get("twitter_thread",[])[:3], 1):
                    st.markdown(f"**{i}.** {tw}")
                if len(s.get("twitter_thread",[])) > 3:
                    st.caption(f"… {len(s['twitter_thread'])-3} more tweets")

            with tbsky:
                bsky = s.get("bluesky_post","")
                if not bsky:
                    bsky = (s.get("linkedin_post","")[:280] + "…")
                st.markdown(_img(_img_url, topic, "280px"), unsafe_allow_html=True)
                st.markdown(
                    f"<div class='content-block' style='font-size:0.8rem'>{bsky}</div>",
                    unsafe_allow_html=True,
                )
                st.caption(f"{len(bsky)}/300 chars")

            with ttg:
                tg = s.get("telegram_post","") or s.get("linkedin_post","")[:1020]
                st.markdown(_img(_img_url, topic, "280px"), unsafe_allow_html=True)
                st.markdown(
                    f"<div class='content-block' style='font-size:0.8rem'>"
                    f"{tg[:500]}{'…' if len(tg)>500 else ''}</div>",
                    unsafe_allow_html=True,
                )
                st.caption(f"{len(tg)}/1024 chars")

            # ── Action buttons — RULE:
            # Published platform = done, Rejected platform = done
            # Only show buttons for platforms that are NEITHER published NOR rejected
            # ─────────────────────────────────────────────────────────────────
            st.divider()

            if n_published == n_total:
                # Every platform published — fully done
                st.markdown(
                    "<div style='padding:6px 12px;background:#0f2a1a;border-radius:6px;"
                    "font-size:0.78rem;color:#4ade80'>✅ All platforms published</div>",
                    unsafe_allow_html=True,
                )
                st.caption(f"`{sid[:16]}…`")

            elif status == "rejected" and n_published == 0:
                # Rejected with NOTHING published — offer re-open only in this case
                st.markdown(
                    f"<div style='padding:6px 12px;background:#2a0f0f;border-radius:6px;"
                    f"font-size:0.78rem;color:#f87171;margin-bottom:8px'>"
                    f"✕ Rejected — {s.get('reviewer_notes','')}"
                    "</div>",
                    unsafe_allow_html=True,
                )
                col_reopen, col_id = st.columns([2, 3])
                if col_reopen.button("↩ Re-open for editing",
                                      key=f"reopen_{sid[:8]}",
                                      use_container_width=True):
                    res = review_action(sid, "approve",
                                        reviewer_notes="Re-opened from history")
                    if res.get("success"):
                        st.session_state["last_session_id"] = sid
                        st.session_state["page"] = "Review"
                        st.rerun()
                col_id.caption(f"`{sid[:16]}…`")

            elif status == "rejected" and n_published > 0:
                # Some published, rest rejected — all are in final state, no action needed
                st.markdown(
                    f"<div style='padding:6px 12px;background:#1a1420;border-radius:6px;"
                    f"font-size:0.78rem;color:#8a7ab0'>"
                    f"✅ {n_published} published · ✕ {n_total - n_published} rejected"
                    "</div>",
                    unsafe_allow_html=True,
                )
                st.caption(f"`{sid[:16]}…`")

            else:
                # Has platforms that are NEITHER published NOR rejected — show action buttons
                if n_published > 0:
                    st.markdown(
                        f"<div style='padding:6px 12px;background:#1a2a1a;border-radius:6px;"
                        f"font-size:0.75rem;color:#86efac;margin-bottom:8px'>"
                        f"✅ {n_published} published · {n_unpublished} not yet published</div>",
                        unsafe_allow_html=True,
                    )

                # Single action: go to publish. Per-platform reject is handled
                # by the ✕ Reject buttons inside each platform card above.
                btn_label = "→ Continue Publishing" if n_published > 0 else "→ Review & Publish"
                col_rev, col_id = st.columns([3, 2])

                with col_rev:
                    if st.button(btn_label, key=f"rev_{sid[:8]}",
                                  use_container_width=True, type="primary"):
                        st.session_state["last_session_id"] = sid
                        if status in ["approved","edited"]:
                            st.session_state["review_mode"]        = "publish"
                            st.session_state["publish_session_id"] = sid
                        else:
                            st.session_state["review_mode"] = None
                        st.session_state["page"] = "Review"
                        st.rerun()

                with col_id:
                    st.caption(f"`{sid[:16]}…`  ·  reject platforms individually above")