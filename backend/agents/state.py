# backend/agents/state.py
# Shared state TypedDict — every agent reads from and writes to this.

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
import time
import operator
from typing import TypedDict, Optional, List, Annotated, Dict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class ContentState(TypedDict):
    # ── Session ─────────────────────────────────────────────────────────────
    session_id:          str
    topic:               str
    tone:                str
    target_platforms:    List[str]
    additional_context:  str          # Optional extra instructions from user

    # ── Pipeline control ────────────────────────────────────────────────────
    current_agent:       str
    rewrite_count:       int
    max_retries:         int
    hitl_status:         str
    error:               Optional[str]  # Set by supervisor on validation failure; router reads it
    pipeline_start_time: float        # Used for elapsed time calculation
    messages:            Annotated[List[BaseMessage], add_messages]

    # ── Research ────────────────────────────────────────────────────────────
    research_data:       str
    sources:             List[str]
    search_queries:      List[str]

    # ── Critique ────────────────────────────────────────────────────────────
    critique_score:      float
    critique_feedback:   str
    needs_rewrite:       bool       # Router reads this to decide rewrite vs format

    # ── Rewrite tracking ────────────────────────────────────────────────────
    rewrite_history:     List[dict] # Each rewrite attempt's before/after
    search_queries_used: List[str]  # Queries the supervisor prepared

    # ── Generated content ───────────────────────────────────────────────────
    blog_post:           str
    linkedin_post:       str
    twitter_thread:      List[str]
    bluesky_post:        str    # Sharp, opinionated, 220-295 chars
    telegram_post:       str    # HTML, image caption format, 800-1000 chars

    # ── Content metadata ────────────────────────────────────────────────────
    blog_word_count:     int
    linkedin_char_count: int
    twitter_tweet_count: int
    bluesky_char_count:  int
    telegram_char_count: int

    # ── Observability: REAL token + latency tracking ───────────────────────
    # Annotated with operator.add so each agent's contribution ACCUMULATES
    # across the graph (LangGraph reducer pattern). These capture actual
    # token counts from Groq's usage_metadata, not estimates.
    total_input_tokens:  Annotated[int, operator.add]
    total_output_tokens: Annotated[int, operator.add]
    # Per-agent timing + tokens: {"research": {"latency_ms": ..., "tokens": ...}}
    agent_metrics:       Annotated[List[dict], operator.add]


def create_initial_state(
    topic: str,
    tone: str = "professional",
    target_platforms: Optional[List[str]] = None,
    session_id: Optional[str] = None,
    additional_context: Optional[str] = None,   # ← was missing, caused the 500
) -> ContentState:
    return ContentState(
        # Session
        session_id=session_id or str(uuid.uuid4()),
        topic=topic,
        tone=tone,
        target_platforms=target_platforms or ["blog", "linkedin", "twitter"],
        additional_context=additional_context or "",

        # Pipeline
        current_agent="supervisor",
        rewrite_count=0,
        max_retries=3,
        hitl_status="pending",
        error=None,
        pipeline_start_time=time.time(),
        messages=[],

        # Research
        research_data="",
        sources=[],
        search_queries=[],

        # Critique
        critique_score=0.0,
        critique_feedback="",
        needs_rewrite=False,

        # Rewrite tracking
        rewrite_history=[],
        search_queries_used=[],

        # Content
        blog_post="",
        linkedin_post="",
        twitter_thread=[],
        bluesky_post="",
        telegram_post="",

        # Metadata
        blog_word_count=0,
        linkedin_char_count=0,
        twitter_tweet_count=0,
        bluesky_char_count=0,
        telegram_char_count=0,

        # Observability — real token + latency tracking
        total_input_tokens=0,
        total_output_tokens=0,
        agent_metrics=[],
    )