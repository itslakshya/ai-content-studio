# backend/database/db.py

import sqlite3
import os
import threading
from pathlib import Path

DB_DIR  = Path("./data")
DB_PATH = DB_DIR / "content_studio.db"

SCHEMA_VERSION = 4  # Increment when schema changes

# Thread-local storage for connections
_local = threading.local()


def get_connection() -> sqlite3.Connection:
    """
    Thread-safe connection getter.
    Each thread gets its own connection (SQLite requirement).
    WAL mode enables concurrent reads.
    """
    if not hasattr(_local, "conn") or _local.conn is None:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
        conn.row_factory = sqlite3.Row           # Dict-like rows
        conn.execute("PRAGMA journal_mode=WAL")  # Crash-safe writes
        conn.execute("PRAGMA foreign_keys=ON")   # Referential integrity
        conn.execute("PRAGMA busy_timeout=5000") # Wait 5s on locks
        _local.conn = conn
    return _local.conn


def get_engine():
    """Alias for compatibility."""
    return get_connection()


def init_db():
    """
    Initialize database — create tables if they don't exist.
    Uses idempotent CREATE IF NOT EXISTS + schema versioning.
    """
    conn = get_connection()

    # Schema version tracking
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    current = conn.execute(
        "SELECT MAX(version) FROM schema_version"
    ).fetchone()[0] or 0

    if current < 1:
        _migrate_v1(conn)

    if current < 2:
        _migrate_v2(conn)

    if current < 3:
        _migrate_v3(conn)

    if current < 4:
        _migrate_v4(conn)

    conn.commit()
    print(f"✅ Database ready: {DB_PATH} (schema v{SCHEMA_VERSION})")
    return conn


def _migrate_v1(conn: sqlite3.Connection):
    """V1: Core tables — sessions, publishes, pipeline runs."""
    print("   📦 Applying migration v1: core tables...")

    conn.executescript("""
        -- Sessions table — stores HITL sessions with all generated content
        CREATE TABLE IF NOT EXISTS sessions (
            session_id    TEXT PRIMARY KEY,
            topic         TEXT NOT NULL,
            tone          TEXT NOT NULL DEFAULT 'professional',
            status        TEXT NOT NULL DEFAULT 'pending',
            critique_score REAL DEFAULT 0.0,
            rewrite_count  INTEGER DEFAULT 0,

            -- Generated content stored as TEXT (JSON for lists)
            blog_post      TEXT DEFAULT '',
            linkedin_post  TEXT DEFAULT '',
            twitter_thread TEXT DEFAULT '[]',
            bluesky_post   TEXT DEFAULT '',
            telegram_post  TEXT DEFAULT '',

            -- Metadata
            sources        TEXT DEFAULT '[]',
            research_data  TEXT DEFAULT '',
            target_platforms TEXT DEFAULT '[]',
            reviewer_notes TEXT DEFAULT '',
            human_edits    TEXT DEFAULT '{}',

            -- Cached cover image URL (generated once, reused everywhere)
            cover_image_url TEXT DEFAULT '',

            -- Timestamps
            created_at     REAL NOT NULL,
            reviewed_at    REAL,
            updated_at     REAL,

            -- Indexes created below
            CHECK (status IN ('pending','approved','edited','rejected'))
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_status
            ON sessions(status);
        CREATE INDEX IF NOT EXISTS idx_sessions_created
            ON sessions(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_sessions_topic
            ON sessions(topic);

        -- Per-platform publish records
        CREATE TABLE IF NOT EXISTS publishes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id   TEXT NOT NULL,
            platform     TEXT NOT NULL,
            url          TEXT DEFAULT '',
            post_id      TEXT DEFAULT '',
            image_url    TEXT DEFAULT '',
            published_at REAL NOT NULL,
            success      INTEGER DEFAULT 1,
            error        TEXT DEFAULT '',

            FOREIGN KEY (session_id) REFERENCES sessions(session_id),
            UNIQUE(session_id, platform)
        );

        CREATE INDEX IF NOT EXISTS idx_publishes_session
            ON publishes(session_id);

        -- Pipeline run metrics for observability
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            run_id        TEXT PRIMARY KEY,
            session_id    TEXT NOT NULL,
            topic         TEXT NOT NULL,
            status        TEXT DEFAULT 'running',
            total_latency_s REAL DEFAULT 0,
            total_tokens  INTEGER DEFAULT 0,
            critique_score REAL DEFAULT 0,
            rewrite_count INTEGER DEFAULT 0,
            cached        INTEGER DEFAULT 0,
            error         TEXT DEFAULT '',
            started_at    REAL NOT NULL,
            completed_at  REAL,

            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        );

        -- Per-agent call timing within a pipeline run
        CREATE TABLE IF NOT EXISTS agent_calls (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id     TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            latency_ms REAL DEFAULT 0,
            tokens     INTEGER DEFAULT 0,
            success    INTEGER DEFAULT 1,
            error      TEXT DEFAULT '',
            called_at  REAL NOT NULL,

            FOREIGN KEY (run_id) REFERENCES pipeline_runs(run_id)
        );

        CREATE INDEX IF NOT EXISTS idx_agent_calls_run
            ON agent_calls(run_id);
    """)

    conn.execute("INSERT INTO schema_version (version) VALUES (1)")
    print("   ✅ Migration v1 applied")


def _migrate_v2(conn: sqlite3.Connection):
    """V2: Add estimated cost tracking."""
    print("   📦 Applying migration v2: cost tracking...")

    try:
        conn.execute(
            "ALTER TABLE pipeline_runs ADD COLUMN estimated_cost_usd REAL DEFAULT 0"
        )
    except sqlite3.OperationalError:
        pass  # Column already exists

    conn.execute("INSERT INTO schema_version (version) VALUES (2)")
    print("   ✅ Migration v2 applied")


def _migrate_v3(conn: sqlite3.Connection):
    """
    V3: Remove foreign key constraints from observability tables.

    INTERVIEW NOTE:
    Pipeline runs and agent calls are observability data — they should
    persist independently of the session lifecycle. The original FK
    constraint caused failures when tracker.start_run() was called before
    the session was inserted (a race condition in the pipeline ordering).

    SQLite can't ALTER TABLE to drop constraints, so we recreate the tables.
    We keep session_id as a regular column (still queryable, just not
    enforced as a FK).
    """
    print("   📦 Applying migration v3: remove FK constraints from observability...")

    conn.executescript("""
        -- Rebuild pipeline_runs without FK
        CREATE TABLE IF NOT EXISTS pipeline_runs_new (
            run_id          TEXT PRIMARY KEY,
            session_id      TEXT NOT NULL,
            topic           TEXT NOT NULL,
            status          TEXT DEFAULT 'running',
            total_latency_s REAL DEFAULT 0,
            total_tokens    INTEGER DEFAULT 0,
            critique_score  REAL DEFAULT 0,
            rewrite_count   INTEGER DEFAULT 0,
            cached          INTEGER DEFAULT 0,
            error           TEXT DEFAULT '',
            started_at      REAL NOT NULL,
            completed_at    REAL,
            estimated_cost_usd REAL DEFAULT 0
        );

        INSERT INTO pipeline_runs_new
        SELECT run_id, session_id, topic, status, total_latency_s,
               total_tokens, critique_score, rewrite_count, cached,
               error, started_at, completed_at, estimated_cost_usd
        FROM pipeline_runs;

        DROP TABLE pipeline_runs;
        ALTER TABLE pipeline_runs_new RENAME TO pipeline_runs;

        CREATE INDEX IF NOT EXISTS idx_pipeline_runs_session
            ON pipeline_runs(session_id);
        CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started
            ON pipeline_runs(started_at DESC);

        -- Rebuild agent_calls without FK
        CREATE TABLE IF NOT EXISTS agent_calls_new (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id     TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            latency_ms REAL DEFAULT 0,
            tokens     INTEGER DEFAULT 0,
            success    INTEGER DEFAULT 1,
            error      TEXT DEFAULT '',
            called_at  REAL NOT NULL
        );

        INSERT INTO agent_calls_new (run_id, agent_name, latency_ms,
                                      tokens, success, error, called_at)
        SELECT run_id, agent_name, latency_ms, tokens, success, error, called_at
        FROM agent_calls;

        DROP TABLE agent_calls;
        ALTER TABLE agent_calls_new RENAME TO agent_calls;

        CREATE INDEX IF NOT EXISTS idx_agent_calls_run
            ON agent_calls(run_id);

        -- Also: remove FK from publishes (same reasoning — publish records
        -- should survive even if a session row is deleted)
        CREATE TABLE IF NOT EXISTS publishes_new (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id   TEXT NOT NULL,
            platform     TEXT NOT NULL,
            url          TEXT DEFAULT '',
            post_id      TEXT DEFAULT '',
            image_url    TEXT DEFAULT '',
            published_at REAL NOT NULL,
            success      INTEGER DEFAULT 1,
            error        TEXT DEFAULT '',
            UNIQUE(session_id, platform)
        );

        INSERT INTO publishes_new (session_id, platform, url, post_id,
                                    image_url, published_at, success, error)
        SELECT session_id, platform, url, post_id, image_url,
               published_at, success, error
        FROM publishes;

        DROP TABLE publishes;
        ALTER TABLE publishes_new RENAME TO publishes;

        CREATE INDEX IF NOT EXISTS idx_publishes_session
            ON publishes(session_id);
    """)

    conn.execute("INSERT INTO schema_version (version) VALUES (3)")
    print("   ✅ Migration v3 applied — FK constraints removed")


def _migrate_v4(conn: sqlite3.Connection):
    """
    V4: Add cover_image_url to sessions.

    Why: AI image generation is non-deterministic across different image
    dimensions (blog 1200x630 vs bluesky 1200x675 produce different renders
    for the same prompt+seed). Caching the final URL once and reusing it
    everywhere — preview, review, and publish — guarantees the SAME image is
    shown and posted across the entire content lifecycle, and it survives
    server restarts (unlike the in-memory prompt cache).
    """
    print("   📦 Applying migration v4: cached cover image URL...")
    # Add column if it doesn't already exist
    cols = [r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()]
    if "cover_image_url" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN cover_image_url TEXT DEFAULT ''")
    conn.execute("INSERT INTO schema_version (version) VALUES (4)")
    print("   ✅ Migration v4 applied — cover_image_url column added")


def close_connection():
    """Close thread-local connection."""
    if hasattr(_local, "conn") and _local.conn:
        _local.conn.close()
        _local.conn = None