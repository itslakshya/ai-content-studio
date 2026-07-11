# tests/test_security.py
# Run: pytest tests/test_security.py -v

import pytest
import time
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from security.rate_limiter import RateLimiter, TokenBucket


# ── Token bucket tests ────────────────────────────────────────────────────────
def test_bucket_starts_full():
    bucket = TokenBucket(capacity=10.0, refill_rate=1.0)
    assert bucket.available >= 9.9  # Allow tiny float variance


def test_bucket_consume_allows():
    bucket = TokenBucket(capacity=5.0, refill_rate=1.0)
    assert bucket.consume() == True
    assert bucket.consume() == True


def test_bucket_exhaustion():
    bucket = TokenBucket(capacity=3.0, refill_rate=0.1)
    assert bucket.consume() == True
    assert bucket.consume() == True
    assert bucket.consume() == True
    assert bucket.consume() == False  # Exhausted


def test_bucket_retry_after():
    bucket = TokenBucket(capacity=1.0, refill_rate=1.0)
    bucket.consume()  # Empty it
    assert bucket.retry_after > 0


def test_rate_limiter_per_key_isolation():
    limiter = RateLimiter()
    result_a = limiter.check("key-alpha-test")
    result_b = limiter.check("key-beta-test")
    assert result_a["allowed"] == True
    assert result_b["allowed"] == True
    assert result_a["tokens_remaining"] == result_b["tokens_remaining"]


def test_rate_limiter_response_shape():
    limiter = RateLimiter()
    result = limiter.check("test-key-shape")
    assert "allowed" in result
    assert "tokens_remaining" in result
    assert "retry_after" in result
    assert "limit" in result


# ── HITL store tests ──────────────────────────────────────────────────────────
def test_hitl_create_and_retrieve():
    from hitl.review import HITLStore, HITLStatus
    import uuid
    store = HITLStore()
    fake = {
        "session_id": str(uuid.uuid4()),
        "topic": "Test Topic",
        "tone": "professional",
        "target_platforms": ["blog"],
        "blog_post": "Test blog",
        "linkedin_post": "Test linkedin",
        "twitter_thread": ["tweet 1"],
        "critique_score": 0.85,
        "rewrite_count": 0,
        "sources": [],
        "research_data": "test",
    }
    session = store.create_session(fake)
    assert session.status == HITLStatus.PENDING
    retrieved = store.get_session(session.session_id)
    assert retrieved is not None
    assert retrieved.topic == "Test Topic"


def test_hitl_approve():
    from hitl.review import HITLStore, HITLStatus
    import uuid
    store = HITLStore()
    fake = {
        "session_id": str(uuid.uuid4()),
        "topic": "Approve Test",
        "tone": "casual",
        "target_platforms": ["twitter"],
        "blog_post": "", "linkedin_post": "",
        "twitter_thread": ["tweet"], "critique_score": 0.9,
        "rewrite_count": 0, "sources": [], "research_data": "",
    }
    session = store.create_session(fake)
    approved = store.approve(session.session_id, "Looks good")
    assert approved.status == HITLStatus.APPROVED
    assert approved.reviewer_notes == "Looks good"


def test_hitl_reject():
    from hitl.review import HITLStore, HITLStatus
    import uuid
    store = HITLStore()
    fake = {
        "session_id": str(uuid.uuid4()),
        "topic": "Reject Test",
        "tone": "casual",
        "target_platforms": ["twitter"],
        "blog_post": "", "linkedin_post": "",
        "twitter_thread": ["tweet"], "critique_score": 0.5,
        "rewrite_count": 2, "sources": [], "research_data": "",
    }
    session = store.create_session(fake)
    rejected = store.reject(session.session_id, "Off brand")
    assert rejected.status == HITLStatus.REJECTED


def test_hitl_edit_and_approve():
    from hitl.review import HITLStore, HITLStatus
    import uuid
    store = HITLStore()
    fake = {
        "session_id": str(uuid.uuid4()),
        "topic": "Edit Test",
        "tone": "professional",
        "target_platforms": ["blog"],
        "blog_post": "Original blog content",
        "linkedin_post": "", "twitter_thread": [],
        "critique_score": 0.8, "rewrite_count": 0,
        "sources": [], "research_data": "",
    }
    session = store.create_session(fake)
    edited = store.edit_and_approve(
        session.session_id,
        blog_post="Edited blog content",
    )
    assert edited.status == HITLStatus.EDITED
    assert edited.blog_post == "Edited blog content"
    assert "blog_post" in edited.human_edits
    assert edited.human_edits["blog_post"]["original"] == "Original blog content"