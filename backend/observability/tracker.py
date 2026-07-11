# backend/observability/tracker.py

import time
import uuid
from typing import Optional

from database.repositories import MetricsRepository

# Cost per 1M tokens for Groq Llama 3.3 70B
COST_PER_1M_TOKENS = 0.59


class PipelineTracker:
    """
    Tracks pipeline metrics with SQLite persistence.
    Survives restarts — all historical data preserved.
    """

    def __init__(self):
        self._repo = MetricsRepository()

    def start_run(self, session_id: str, topic: str) -> str:
        """Start tracking a pipeline run. Returns the run_id."""
        run_id = str(uuid.uuid4())
        self._repo.start_run(run_id, session_id, topic)
        return run_id

    def end_run(
        self,
        run_id: str,
        status: str = "complete",
        total_latency_s: float = 0,
        total_tokens: int = 0,        # REAL total (input+output) from API
        input_tokens: int = 0,        # REAL input tokens
        output_tokens: int = 0,       # REAL output tokens
        agent_metrics: list = None,   # per-agent [{agent, latency_ms, input_tokens, output_tokens}]
        critique_score: float = 0,
        rewrite_count: int = 0,
        cached: bool = False,
        error: str = "",
        blog_post: str = "",
        linkedin_post: str = "",
        twitter_thread: list = None,
        bluesky_post: str = "",
        telegram_post: str = "",
    ) -> None:
        """
        End a pipeline run with final metrics.

        Token strategy:
          1. If real total_tokens provided (from Groq usage_metadata) → use exact
          2. Else if cached → 0 tokens (no LLM calls happened)
          3. Else → fall back to length-based estimate (only if API gave nothing)
        """
        if total_tokens > 0:
            # REAL tokens captured from the API — exact, varies per run
            final_tokens = total_tokens
            token_source = "measured"
        elif cached:
            final_tokens = 0
            token_source = "cached"
        else:
            # Fallback estimate ONLY when the API returned no usage data
            total_words = (
                len(blog_post.split()) +
                len(linkedin_post.split()) +
                sum(len(t.split()) for t in (twitter_thread or [])) +
                len(bluesky_post.split()) +
                len(telegram_post.split())
            )
            n_calls = 7 + rewrite_count
            final_tokens = int(total_words * 0.75) + (n_calls * 2000)
            token_source = "estimated"

        estimated_cost = (final_tokens / 1_000_000) * COST_PER_1M_TOKENS

        self._repo.end_run(
            run_id=run_id,
            status=status,
            total_latency_s=total_latency_s,
            total_tokens=final_tokens,
            critique_score=critique_score,
            rewrite_count=rewrite_count,
            cached=cached,
            error=error,
            estimated_cost=estimated_cost,
        )

        # Persist per-agent metrics (real latency + tokens from each agent)
        if agent_metrics:
            for m in agent_metrics:
                agent_tok = m.get("input_tokens", 0) + m.get("output_tokens", 0)
                self._repo.record_agent_call(
                    run_id=run_id,
                    agent_name=m.get("agent", "unknown"),
                    latency_ms=m.get("latency_ms", 0),
                    tokens=agent_tok,
                    success=True,
                    error="",
                )

        print(f"   📊 Tracker: {final_tokens} tokens ({token_source}), "
              f"${estimated_cost:.5f}, {len(agent_metrics or [])} agents recorded")

    def start_agent(self, run_id: str, agent_name: str) -> float:
        """Record agent start time. Returns start_time for later use."""
        return time.time()

    def end_agent(
        self,
        run_id: str,
        agent_name: str,
        start_time: float,
        tokens: int = 0,
        success: bool = True,
        error: str = "",
    ) -> None:
        """Record agent completion with latency."""
        latency_ms = (time.time() - start_time) * 1000
        self._repo.record_agent_call(
            run_id=run_id,
            agent_name=agent_name,
            latency_ms=latency_ms,
            tokens=tokens,
            success=success,
            error=error,
        )

    def get_summary(self) -> dict:
        """Get aggregated metrics for the observability dashboard."""
        summary = self._repo.get_summary()
        summary["agent_avg_latency_ms"] = self._repo.get_agent_avg_latency()
        return summary

    def get_runs(self, limit: int = 50) -> list:
        """Get recent pipeline runs with agent call details."""
        return self._repo.get_runs(limit=limit)


# Singleton
_tracker: Optional[PipelineTracker] = None

def get_tracker() -> PipelineTracker:
    global _tracker
    if _tracker is None:
        _tracker = PipelineTracker()
    return _tracker