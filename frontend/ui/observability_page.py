# frontend/ui/observability_page.py
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from components.api_client import get_headers, get_base_url
import requests


def _get(endpoint):
    try:
        r = requests.get(f"{get_base_url()}/observability/{endpoint}",
                         headers=get_headers(), timeout=10)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


def show():
    st.markdown("""
    <h1 style="font-size:1.8rem;font-weight:700;letter-spacing:-0.02em;margin:0 0 4px;color:#e2e2f0">
        Observability
    </h1>
    <p style="color:#555570;font-size:0.75rem;margin:0 0 24px;text-transform:uppercase;letter-spacing:0.04em">
        Tokens · Latency · Pipeline Metrics
    </p>
    """, unsafe_allow_html=True)

    col_r, col_note = st.columns([1, 5])
    with col_r:
        if st.button("↻  Refresh", use_container_width=True):
            st.rerun()
    with col_note:
        st.caption("Metrics persisted in SQLite — survives restarts")

    summary = _get("summary")
    if not summary or summary.get("total_runs", 0) == 0:
        st.info("No runs yet. Generate some content first.")
        return

    st.divider()

    # ── Overview ──────────────────────────────────────────────────────────────
    c1,c2,c3,c4,c5,c6 = st.columns(6)
    c1.metric("Runs",        summary.get("total_runs",0))
    c2.metric("Completed",   summary.get("completed",0))
    c3.metric("Errors",      summary.get("errors",0))
    c4.metric("Cache Hits",  summary.get("cached_hits",0))
    c5.metric("Cache Rate",  f"{summary.get('cache_hit_rate_pct',0)}%")
    c6.metric("Avg Latency", f"{summary.get('avg_latency_s',0)}s")

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    c1,c2,c3,c4 = st.columns(4)
    tokens = int(summary.get("total_tokens",0) or 0)
    cost   = summary.get("estimated_cost_usd",0)
    c1.metric("Total Tokens",  f"{tokens:,}")
    c2.metric("Est. Cost",     f"${cost:.4f}")
    c3.metric("Avg Score",     f"{summary.get('avg_critique_score',0):.2f}")
    c4.metric("Avg Rewrites",  summary.get("avg_rewrites",0))

    st.caption(
        "Token counts are REAL — captured from Groq's usage_metadata on every LLM call "
        "and accumulated across the pipeline. Cost: Llama 3.3 70B at $0.59/1M tokens."
    )
    st.caption(
        "Score variance is low by design — the Critique Agent uses temperature=0.0 "
        "(deterministic). 0.80–0.87 = consistently good content above the 0.75 threshold."
    )

    # ── Agent latency ─────────────────────────────────────────────────────────
    agent_lats = summary.get("agent_avg_latency_ms", {})
    if agent_lats:
        st.divider()
        st.markdown(
            "<p style='font-size:0.7rem;text-transform:uppercase;letter-spacing:0.06em;"
            "color:#555570;margin-bottom:12px'>Agent Avg Latency</p>",
            unsafe_allow_html=True,
        )
        ORDER  = ["supervisor","research","critique","rewrite","format"]
        LABELS = {"supervisor":"Supervisor","research":"Research",
                  "critique":"Critique","rewrite":"Rewrite","format":"Format"}
        present = [a for a in ORDER if a in agent_lats] + \
                  [a for a in agent_lats if a not in ORDER]

        cols = st.columns(max(len(present), 1))
        for i, agent in enumerate(present):
            ms  = agent_lats[agent]
            lbl = f"{ms:.0f}ms" if ms < 1000 else f"{ms/1000:.1f}s"
            cols[i].metric(LABELS.get(agent, agent), lbl)

        import pandas as pd
        df = pd.DataFrame({
            "Agent": [LABELS.get(a,a) for a in present],
            "ms":    [agent_lats[a] for a in present],
        })
        st.bar_chart(df.set_index("Agent"), height=200)
        st.caption("Research is slowest (web search + RAG retrieval). "
                   "Supervisor is fastest (validation only, no LLM call).")

    # ── Per-run table ─────────────────────────────────────────────────────────
    st.divider()
    st.markdown(
        "<p style='font-size:0.7rem;text-transform:uppercase;letter-spacing:0.06em;"
        "color:#555570;margin-bottom:12px'>Per-Session Runs</p>",
        unsafe_allow_html=True,
    )

    runs_data = _get("runs")
    runs      = runs_data.get("runs", [])
    if not runs:
        st.info("No runs recorded.")
        return

    col_f, _ = st.columns(2)
    with col_f:
        sf = st.multiselect(
            "Status filter",
            ["complete","running","error"],
            default=["complete","running","error"],
            label_visibility="collapsed",
        )

    filtered = [r for r in runs if r.get("status") in sf]
    st.caption(f"{len(filtered)} of {len(runs)} runs")

    for run in filtered:
        status  = run.get("status","?")
        cached  = run.get("cached",False)
        score   = run.get("critique_score",0)
        topic   = run.get("topic","?")[:50]
        latency = round(float(run.get("total_latency_s",0) or 0), 1)
        tokens  = int(run.get("total_tokens",0) or 0)  # int avoids "-0" display
        rewrites = run.get("rewrite_count",0)
        sid     = run.get("session_id","")[:12]

        icon   = {"complete":"✓","running":"◎","error":"✕"}.get(status,"·")
        badge  = "  ⚡ cached" if cached else ""
        lat_str = "cached" if cached else f"{latency}s"

        with st.expander(
            f"{icon}  {topic}  ·  {lat_str}  ·  score {score:.2f}  ·  ~{tokens:,} tokens{badge}",
        ):
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Latency",  lat_str)
            c2.metric("Score",    f"{score:.2f}")
            c3.metric("Rewrites", rewrites)
            c4.metric("Tokens",   f"~{tokens:,}")

            if tokens > 0:
                cost_est = tokens/1_000_000 * 0.59
                st.caption(f"Est. cost: ${cost_est:.5f}")

            st.caption(f"Session `{sid}…` · cached: {cached}")

            if run.get("error"):
                st.error(run["error"])

            calls = run.get("agent_calls",[])
            if calls:
                st.markdown("<small style='color:#555570'>Agent timeline:</small>",
                            unsafe_allow_html=True)
                for call in calls:
                    name = call.get("agent","?")
                    ms   = call.get("latency_ms",0)
                    tok  = int(call.get("tokens",0) or 0)
                    ok   = call.get("success",True)
                    icon2 = "✓" if ok else "✕"
                    ms_s  = f"{ms:.0f}ms" if ms < 1000 else f"{ms/1000:.1f}s"
                    st.markdown(
                        f"<div style='padding:4px 0;font-size:0.78rem;color:#6c6c8a'>"
                        f"{icon2} <strong style='color:#b4b4cc'>{name}</strong> "
                        f"— {ms_s}"
                        f"{'  ·  ~'+str(tok)+' tokens' if tok else ''}</div>",
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("Agent timeline will appear for future runs")