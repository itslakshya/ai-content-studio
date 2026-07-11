# backend/hitl/review.py

import time
from enum import Enum
from typing import Optional, List

from database.repositories import SessionRepository, PublishRepository


class HITLStatus(str, Enum):
    PENDING  = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED   = "edited"


class HITLStore:
    """
    Business logic layer for content review workflow.
    Uses SessionRepository for persistence (database-backed).
    """

    def __init__(self):
        self._session_repo = SessionRepository()
        self._publish_repo = PublishRepository()

    def create_session(self, state: dict) -> dict:
        """Create a new HITL session from pipeline output."""
        session_data = {
            "session_id":       state.get("session_id", ""),
            "topic":            state.get("topic", ""),
            "tone":             state.get("tone", "professional"),
            "target_platforms": state.get("target_platforms", []),
            "blog_post":        state.get("blog_post", ""),
            "linkedin_post":    state.get("linkedin_post", ""),
            "twitter_thread":   state.get("twitter_thread", []),
            "bluesky_post":     state.get("bluesky_post", ""),
            "telegram_post":    state.get("telegram_post", ""),
            "critique_score":   state.get("critique_score", 0.0),
            "rewrite_count":    state.get("rewrite_count", 0),
            "sources":          state.get("sources", []),
            "research_data":    state.get("research_data", ""),
            "status":           "pending",
            "created_at":       time.time(),
            "reviewer_notes":   "",
            "human_edits":      {},
        }
        self._session_repo.save(session_data)
        print(f"📋 HITL session created: {session_data['session_id'][:8]}... "
              f"Topic: '{session_data['topic']}' Status: pending")
        return session_data

    def get_session(self, session_id: str) -> Optional[dict]:
        """Get a session by ID."""
        return self._session_repo.get(session_id)

    def approve(self, session_id: str, reviewer_notes: str = "") -> Optional[dict]:
        """Approve content for publishing."""
        session = self._session_repo.get(session_id)
        if not session:
            return None
        self._session_repo.update_status(
            session_id, "approved", reviewer_notes=reviewer_notes
        )
        print(f"✅ HITL APPROVED: {session_id[:8]}... '{session['topic']}'")
        return self._session_repo.get(session_id)

    def reject(self, session_id: str, reviewer_notes: str = "") -> Optional[dict]:
        """Reject content."""
        session = self._session_repo.get(session_id)
        if not session:
            return None
        self._session_repo.update_status(
            session_id, "rejected", reviewer_notes=reviewer_notes
        )
        print(f"❌ HITL REJECTED: {session_id[:8]}... Reason: {reviewer_notes}")
        return self._session_repo.get(session_id)

    def reopen(self, session_id: str) -> Optional[dict]:
        """
        Revert an approved/edited/rejected session back to 'pending' so the
        user can edit it again. Used by the 'Re-open for editing' button.
        """
        session = self._session_repo.get(session_id)
        if not session:
            return None
        self._session_repo.update_status(session_id, "pending", reviewer_notes="")
        print(f"🔄 HITL REOPENED for editing: {session_id[:8]}...")
        return self._session_repo.get(session_id)

    def edit_and_approve(
        self,
        session_id: str,
        blog_post:      Optional[str] = None,
        linkedin_post:  Optional[str] = None,
        twitter_thread: Optional[List[str]] = None,
        bluesky_post:   Optional[str] = None,
        telegram_post:  Optional[str] = None,
        reviewer_notes: str = "",
    ) -> Optional[dict]:
        """Apply edits and approve."""
        session = self._session_repo.get(session_id)
        if not session:
            return None

        edits = {}
        updates = {}

        if blog_post is not None and blog_post != session.get("blog_post"):
            edits["blog_post"] = True
            updates["blog_post"] = blog_post
        if linkedin_post is not None and linkedin_post != session.get("linkedin_post"):
            edits["linkedin_post"] = True
            updates["linkedin_post"] = linkedin_post
        if twitter_thread is not None and twitter_thread != session.get("twitter_thread"):
            edits["twitter_thread"] = True
            updates["twitter_thread"] = twitter_thread
        if bluesky_post is not None and bluesky_post != session.get("bluesky_post"):
            edits["bluesky_post"] = True
            updates["bluesky_post"] = bluesky_post
        if telegram_post is not None and telegram_post != session.get("telegram_post"):
            edits["telegram_post"] = True
            updates["telegram_post"] = telegram_post

        if updates:
            self._session_repo.update_content(session_id, **updates)

        self._session_repo.update_status(
            session_id, "edited",
            reviewer_notes=reviewer_notes,
            human_edits=edits,
        )
        print(f"✏️  HITL EDITED: {session_id[:8]}... Fields: {list(edits.keys())}")
        return self._session_repo.get(session_id)

    def record_publish(self, session_id: str, platform: str, url: str):
        """Record a successful platform publish."""
        self._publish_repo.record(
            session_id=session_id,
            platform=platform,
            url=url,
            success=True,
        )

    def get_pending(self) -> List[dict]:
        """Get all pending review sessions."""
        return self._session_repo.get_pending()

    def get_all(self) -> List[dict]:
        """Get all sessions (last 50)."""
        return self._session_repo.get_all(limit=50)

    # Legacy compatibility
    def to_dict(self):
        return self.get_all()


_store: Optional[HITLStore] = None

def get_hitl_store() -> HITLStore:
    global _store
    if _store is None:
        _store = HITLStore()
    return _store