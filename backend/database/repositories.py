# backend/database/repositories.py

import json
import time
import uuid
import sqlite3
from typing import Optional, List
from database.db import get_connection


class SessionRepository:
    """
    Manages HITL session persistence.
    Replaces the old in-memory dict with SQLite storage.
    """

    def save(self, session_data: dict) -> None:
        """Insert or update a session (upsert)."""
        conn = get_connection()
        conn.execute("""
            INSERT INTO sessions (
                session_id, topic, tone, status, critique_score, rewrite_count,
                blog_post, linkedin_post, twitter_thread, bluesky_post, telegram_post,
                sources, research_data, target_platforms,
                reviewer_notes, human_edits, created_at, reviewed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                topic=excluded.topic,
                tone=excluded.tone,
                status=excluded.status,
                blog_post=excluded.blog_post,
                linkedin_post=excluded.linkedin_post,
                twitter_thread=excluded.twitter_thread,
                bluesky_post=excluded.bluesky_post,
                telegram_post=excluded.telegram_post,
                sources=excluded.sources,
                research_data=excluded.research_data,
                target_platforms=excluded.target_platforms,
                reviewer_notes=excluded.reviewer_notes,
                human_edits=excluded.human_edits,
                reviewed_at=excluded.reviewed_at,
                updated_at=excluded.updated_at,
                critique_score=excluded.critique_score,
                rewrite_count=excluded.rewrite_count
        """, (
            session_data.get("session_id", str(uuid.uuid4())),
            session_data.get("topic", ""),
            session_data.get("tone", "professional"),
            session_data.get("status", "pending"),
            session_data.get("critique_score", 0.0),
            session_data.get("rewrite_count", 0),
            session_data.get("blog_post", ""),
            session_data.get("linkedin_post", ""),
            json.dumps(session_data.get("twitter_thread", [])),
            session_data.get("bluesky_post", ""),
            session_data.get("telegram_post", ""),
            json.dumps(session_data.get("sources", [])),
            session_data.get("research_data", ""),
            json.dumps(session_data.get("target_platforms", [])),
            session_data.get("reviewer_notes", ""),
            json.dumps(session_data.get("human_edits", {})),
            session_data.get("created_at", time.time()),
            session_data.get("reviewed_at"),
            time.time(),
        ))
        conn.commit()

    def get(self, session_id: str) -> Optional[dict]:
        """Get a single session by ID."""
        conn = get_connection()
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_all(self, limit: int = 50) -> List[dict]:
        """Get all sessions, newest first. Default limit: 50."""
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_pending(self) -> List[dict]:
        """Get sessions awaiting review."""
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM sessions WHERE status = 'pending' ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def update_status(self, session_id: str, status: str,
                      reviewer_notes: str = "", human_edits: dict = None) -> bool:
        """Update session status (approve/reject/edit)."""
        conn = get_connection()
        conn.execute("""
            UPDATE sessions
            SET status = ?, reviewer_notes = ?, human_edits = ?,
                reviewed_at = ?, updated_at = ?
            WHERE session_id = ?
        """, (
            status, reviewer_notes,
            json.dumps(human_edits or {}),
            time.time(), time.time(),
            session_id,
        ))
        conn.commit()
        return conn.total_changes > 0

    def update_content(self, session_id: str, **fields) -> bool:
        """Update specific content fields of a session."""
        conn = get_connection()
        set_parts = []
        values    = []
        for key, val in fields.items():
            if key in ("blog_post", "linkedin_post", "bluesky_post",
                       "telegram_post", "reviewer_notes"):
                set_parts.append(f"{key} = ?")
                values.append(val)
            elif key == "twitter_thread":
                set_parts.append("twitter_thread = ?")
                values.append(json.dumps(val))

        if not set_parts:
            return False

        set_parts.append("updated_at = ?")
        values.append(time.time())
        values.append(session_id)

        conn.execute(
            f"UPDATE sessions SET {', '.join(set_parts)} WHERE session_id = ?",
            values,
        )
        conn.commit()
        return True

    def count_by_status(self) -> dict:
        """Get counts by status."""
        conn = get_connection()
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM sessions GROUP BY status"
        ).fetchall()
        return {r["status"]: r["cnt"] for r in rows}

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert a database row to the dict format HITL store expects."""
        d = dict(row)
        # Parse JSON fields
        for field in ("twitter_thread", "sources", "target_platforms"):
            if field in d and isinstance(d[field], str):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    d[field] = []
        for field in ("human_edits",):
            if field in d and isinstance(d[field], str):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    d[field] = {}
        # Add computed fields
        d["age_seconds"] = round(time.time() - (d.get("created_at") or time.time()), 1)
        # Get published URLs for this session
        d["published_urls"] = self._get_published_urls(d["session_id"])
        return d

    def _get_published_urls(self, session_id: str) -> dict:
        """Get all published platform URLs for a session."""
        conn = get_connection()
        rows = conn.execute(
            "SELECT platform, url FROM publishes WHERE session_id = ? AND success = 1",
            (session_id,)
        ).fetchall()
        return {r["platform"]: r["url"] for r in rows}

    def get_cover_image(self, session_id: str) -> str:
        """Return the cached cover image URL for a session ('' if none yet)."""
        conn = get_connection()
        row = conn.execute(
            "SELECT cover_image_url FROM sessions WHERE session_id = ?",
            (session_id,)
        ).fetchone()
        return (row["cover_image_url"] if row else "") or ""

    def set_cover_image(self, session_id: str, url: str) -> None:
        """
        Persist the cover image URL so the SAME image is reused everywhere
        (preview, review, publish) and survives restarts. Generated once.
        """
        conn = get_connection()
        conn.execute(
            "UPDATE sessions SET cover_image_url = ? WHERE session_id = ?",
            (url, session_id)
        )
        conn.commit()



class PublishRepository:
    """Tracks per-platform publish records."""

    def record(self, session_id: str, platform: str, url: str = "",
               post_id: str = "", image_url: str = "",
               success: bool = True, error: str = "") -> None:
        """Record a publish attempt (success or failure)."""
        conn = get_connection()
        conn.execute("""
            INSERT INTO publishes (session_id, platform, url, post_id,
                                   image_url, published_at, success, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, platform) DO UPDATE SET
                url=excluded.url, post_id=excluded.post_id,
                image_url=excluded.image_url, published_at=excluded.published_at,
                success=excluded.success, error=excluded.error
        """, (
            session_id, platform, url, post_id,
            image_url, time.time(), 1 if success else 0, error,
        ))
        conn.commit()

    def get_for_session(self, session_id: str) -> List[dict]:
        """Get all publish records for a session."""
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM publishes WHERE session_id = ? ORDER BY published_at DESC",
            (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_published_urls(self, session_id: str) -> dict:
        """Get {platform: url} for successful publishes."""
        conn = get_connection()
        rows = conn.execute(
            "SELECT platform, url FROM publishes WHERE session_id = ? AND success = 1",
            (session_id,)
        ).fetchall()
        return {r["platform"]: r["url"] for r in rows}

    def record_rejection(self, session_id: str, platform: str) -> None:
        """
        Record that a specific platform was rejected for this session.
        Uses success=0 with url='rejected:' prefix so it's distinguishable
        from a failed publish attempt.
        """
        conn = get_connection()
        conn.execute("""
            INSERT INTO publishes (session_id, platform, url, published_at, success, error)
            VALUES (?, ?, 'rejected:', ?, 0, 'Rejected by user from history')
            ON CONFLICT(session_id, platform) DO UPDATE SET
                url='rejected:', success=0,
                error='Rejected by user from history',
                published_at=excluded.published_at
        """, (session_id, platform, time.time()))
        conn.commit()

    def get_all_platform_states(self, session_id: str) -> dict:
        """
        Returns full state per platform:
        {platform: {"state": "published"|"rejected"|"unpublished", "url": ...}}
        """
        conn = get_connection()
        rows = conn.execute(
            "SELECT platform, url, success FROM publishes WHERE session_id = ?",
            (session_id,)
        ).fetchall()
        result = {}
        for r in rows:
            if r["success"] == 1:
                result[r["platform"]] = {"state": "published", "url": r["url"]}
            else:
                result[r["platform"]] = {"state": "rejected", "url": ""}
        return result


class MetricsRepository:
    """Stores observability data — pipeline runs and agent timing."""

    def start_run(self, run_id: str, session_id: str, topic: str) -> None:
        """Record a new pipeline run starting."""
        conn = get_connection()
        conn.execute("""
            INSERT INTO pipeline_runs (run_id, session_id, topic, status, started_at)
            VALUES (?, ?, ?, 'running', ?)
        """, (run_id, session_id, topic, time.time()))
        conn.commit()

    def end_run(self, run_id: str, status: str = "complete",
                total_latency_s: float = 0, total_tokens: int = 0,
                critique_score: float = 0, rewrite_count: int = 0,
                cached: bool = False, error: str = "",
                estimated_cost: float = 0) -> None:
        """Record pipeline run completion."""
        conn = get_connection()
        conn.execute("""
            UPDATE pipeline_runs
            SET status = ?, total_latency_s = ?, total_tokens = ?,
                critique_score = ?, rewrite_count = ?, cached = ?,
                error = ?, completed_at = ?, estimated_cost_usd = ?
            WHERE run_id = ?
        """, (
            status, total_latency_s, total_tokens,
            critique_score, rewrite_count, 1 if cached else 0,
            error, time.time(), estimated_cost,
            run_id,
        ))
        conn.commit()

    def record_agent_call(self, run_id: str, agent_name: str,
                          latency_ms: float = 0, tokens: int = 0,
                          success: bool = True, error: str = "") -> None:
        """Record a single agent invocation within a pipeline run."""
        conn = get_connection()
        conn.execute("""
            INSERT INTO agent_calls (run_id, agent_name, latency_ms,
                                      tokens, success, error, called_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (run_id, agent_name, latency_ms, tokens,
              1 if success else 0, error, time.time()))
        conn.commit()

    def get_summary(self) -> dict:
        """
        Get aggregated observability summary.

        IMPORTANT: counts (runs/completed/errors) span ALL rows, but AVERAGES
        (latency, score, rewrites) are computed ONLY over completed, non-cached
        runs. Otherwise orphaned/incomplete runs (0 score, 0 latency) drag the
        averages down — e.g. avg score showing 0.49 instead of the real 0.82.
        Token/cost SUMS are over all real (non-cached) runs.
        """
        conn = get_connection()

        # Counts across everything
        counts = conn.execute("""
            SELECT
                COUNT(*)                           as total_runs,
                SUM(CASE WHEN status='complete' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status='error'    THEN 1 ELSE 0 END) as errors,
                SUM(CASE WHEN cached=1          THEN 1 ELSE 0 END) as cached_hits,
                SUM(total_tokens)                  as total_tokens,
                SUM(estimated_cost_usd)            as total_cost_usd
            FROM pipeline_runs
        """).fetchone()

        # Averages ONLY over completed, non-cached runs (real pipeline executions)
        avgs = conn.execute("""
            SELECT
                ROUND(AVG(total_latency_s), 1)  as avg_latency_s,
                ROUND(AVG(critique_score), 2)   as avg_critique_score,
                ROUND(AVG(rewrite_count), 1)    as avg_rewrites
            FROM pipeline_runs
            WHERE status = 'complete' AND cached = 0
        """).fetchone()

        total  = counts["total_runs"] or 0
        cached = counts["cached_hits"] or 0

        return {
            "total_runs":         total,
            "completed":          counts["completed"] or 0,
            "errors":             counts["errors"] or 0,
            "cached_hits":        cached,
            "cache_hit_rate_pct": round(cached / total * 100, 1) if total > 0 else 0,
            "avg_latency_s":      avgs["avg_latency_s"] or 0,
            "total_tokens":       counts["total_tokens"] or 0,
            "estimated_cost_usd": round(counts["total_cost_usd"] or 0, 6),
            "avg_critique_score": avgs["avg_critique_score"] or 0,
            "avg_rewrites":       avgs["avg_rewrites"] or 0,
        }

    def cleanup_orphaned_runs(self, older_than_seconds: int = 300) -> int:
        """
        Mark stale 'running' runs as 'error'. These are runs where start_run was
        called but end_run never completed (crash, interrupt, or pre-fix bug).
        Leaving them as 'running' clutters the dashboard and skews nothing now
        that averages exclude them, but marking them keeps the UI honest.
        Returns the number of rows updated.
        """
        import time as _t
        conn = get_connection()
        cutoff = _t.time() - older_than_seconds
        cur = conn.execute("""
            UPDATE pipeline_runs
            SET status = 'error', error = 'Incomplete run (never finished)'
            WHERE status = 'running' AND started_at < ?
        """, (cutoff,))
        conn.commit()
        return cur.rowcount

    def get_runs(self, limit: int = 50) -> List[dict]:
        """Get recent pipeline runs with agent call details."""
        conn = get_connection()
        runs = conn.execute(
            "SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT ?",
            (limit,)
        ).fetchall()

        result = []
        for run in runs:
            d = dict(run)
            d["cached"] = bool(d.get("cached"))
            # Get agent calls for this run
            calls = conn.execute(
                "SELECT * FROM agent_calls WHERE run_id = ? ORDER BY called_at",
                (d["run_id"],)
            ).fetchall()
            # Normalize key: DB stores 'agent_name', frontend expects 'agent'
            agent_calls = []
            for c in calls:
                cd = dict(c)
                cd["agent"] = cd.get("agent_name", "unknown")
                agent_calls.append(cd)
            d["agent_calls"] = agent_calls
            result.append(d)

        return result

    def get_agent_avg_latency(self) -> dict:
        """Get average latency per agent across all runs."""
        conn = get_connection()
        rows = conn.execute("""
            SELECT agent_name, ROUND(AVG(latency_ms), 1) as avg_ms
            FROM agent_calls
            GROUP BY agent_name
        """).fetchall()
        return {r["agent_name"]: r["avg_ms"] for r in rows}