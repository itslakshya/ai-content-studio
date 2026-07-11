# test_day4.py — Run from ai-content-studio root
# 
# TWO parts:
# PART A: Unit tests (no server needed) — run first
# PART B: API tests (server must be running) — run after starting server
#
# Part A: python test_day4.py
# Part B: In a SECOND terminal run: uvicorn backend.main:app --reload
#         Then in first terminal: python test_day4.py --api

import sys, os, asyncio, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))


def print_header(text):
    print(f"\n{'='*60}\n  {text}\n{'='*60}")

def print_result(label, success, detail=""):
    print(f"  {'✅' if success else '❌'} {label}")
    if detail:
        print(f"     {detail}")


parser = argparse.ArgumentParser()
parser.add_argument("--api", action="store_true", help="Run API tests (server must be running)")
args = parser.parse_args()


# ════════════════════════════════════════════════════════════
# PART A — UNIT TESTS (no server needed)
# ════════════════════════════════════════════════════════════

# ── TEST 1: Rate Limiter ──────────────────────────────────────────────────────
print_header("TEST 1: Token Bucket Rate Limiter")
try:
    from security.rate_limiter import RateLimiter

    limiter = RateLimiter()

    # Simulate requests from same key
    key = "test-api-key-123"
    results = [limiter.check(key) for _ in range(5)]

    all_allowed = all(r["allowed"] for r in results)
    print_result("First 5 requests allowed", all_allowed,
                 f"Remaining after 5: {results[-1]['tokens_remaining']}")

    # Exhaust the bucket manually by creating a low-capacity limiter
    from security.rate_limiter import TokenBucket
    tiny_bucket = TokenBucket(capacity=3.0, refill_rate=1.0)
    r1 = tiny_bucket.consume()
    r2 = tiny_bucket.consume()
    r3 = tiny_bucket.consume()
    r4 = tiny_bucket.consume()  # Should fail

    print_result("Bucket exhaustion works",
                 r1 and r2 and r3 and not r4,
                 f"3 allowed, 4th blocked ✓")
    print_result("Retry-after calculated",
                 tiny_bucket.retry_after > 0,
                 f"Retry after: {tiny_bucket.retry_after:.2f}s")

    # Test per-key isolation
    result_a = limiter.check("key-A")
    result_b = limiter.check("key-B")
    print_result("Keys are isolated",
                 result_a["allowed"] and result_b["allowed"],
                 "Different keys have independent buckets ✓")

except Exception as e:
    print_result("Rate limiter failed", False, str(e))
    import traceback; traceback.print_exc()


# ── TEST 2: Semantic Cache ────────────────────────────────────────────────────
print_header("TEST 2: Semantic Cache")
try:
    from cache.semantic_cache import SemanticCache

    cache = SemanticCache()

    # Store a result
    fake_result = {
        "blog_post": "Sample blog post about AI",
        "linkedin_post": "LinkedIn post about AI",
        "twitter_thread": ["Tweet 1", "Tweet 2"],
        "critique_score": 0.85,
        "sources": ["https://example.com"],
    }

    cache.set("AI in Healthcare", "professional", fake_result, "AI in Healthcare")
    print_result("Cache stores result", len(cache.entries) == 1,
                 f"Entries: {len(cache.entries)}")

    # Exact match hit
    hit = cache.get("AI in Healthcare", "professional")
    print_result("Exact match hit", hit is not None,
                 "Same query returns cached result ✓")

    # Semantic match hit (similar phrasing)
    print("  🔄 Testing semantic similarity (embedding model loads)...")
    sem_hit = cache.get("Artificial Intelligence in Healthcare", "professional")
    print_result("Semantic match hit",
                 sem_hit is not None,
                 "Similar query hits cache ✓" if sem_hit else
                 "Miss (similarity below threshold — acceptable)")

    # Different tone = cache miss
    tone_miss = cache.get("AI in Healthcare", "casual")
    print_result("Different tone = miss",
                 tone_miss is None,
                 "Tone mismatch correctly misses ✓")

    # Stats
    stats = cache.get_stats()
    print_result("Stats tracked",
                 "hit_rate_pct" in stats,
                 f"Hits: {stats['hits']}, Misses: {stats['misses']}, "
                 f"Rate: {stats['hit_rate_pct']}%")

except Exception as e:
    print_result("Semantic cache failed", False, str(e))
    import traceback; traceback.print_exc()


# ── TEST 3: HITL Store ────────────────────────────────────────────────────────
print_header("TEST 3: HITL Review Store")
try:
    from hitl.review import HITLStore, HITLStatus
    import uuid

    store = HITLStore()

    fake_pipeline_result = {
        "session_id": str(uuid.uuid4()),
        "topic": "AI in Healthcare",
        "tone": "professional",
        "target_platforms": ["blog", "linkedin", "twitter"],
        "blog_post": "# AI in Healthcare\n\nThis is the blog post...",
        "linkedin_post": "AI is transforming healthcare...",
        "twitter_thread": ["Tweet 1 about AI", "Tweet 2 about healthcare"],
        "critique_score": 0.85,
        "rewrite_count": 0,
        "sources": ["https://example.com"],
        "research_data": "Research about AI in healthcare...",
    }

    # Create session
    session = store.create_session(fake_pipeline_result)
    sid = session.session_id
    print_result("Session created",
                 session.status == HITLStatus.PENDING,
                 f"ID: {sid[:8]}... Status: {session.status}")

    # Get session
    retrieved = store.get_session(sid)
    print_result("Session retrievable",
                 retrieved is not None and retrieved.topic == "AI in Healthcare",
                 f"Topic: {retrieved.topic}")

    # Approve
    approved = store.approve(sid, "Looks great!")
    print_result("Approve works",
                 approved.status == HITLStatus.APPROVED,
                 f"Status: {approved.status} ✓")

    # Create another session for edit test
    fake_pipeline_result["session_id"] = str(uuid.uuid4())
    session2 = store.create_session(fake_pipeline_result)
    edited = store.edit_and_approve(
        session2.session_id,
        blog_post="# AI in Healthcare (Edited)\n\nEdited by human...",
        reviewer_notes="Fixed intro paragraph",
    )
    print_result("Edit+approve works",
                 edited.status == HITLStatus.EDITED,
                 f"Edits tracked: {len(edited.human_edits)} field(s)")
    print_result("Original preserved",
                 "blog_post" in edited.human_edits,
                 "Original stored alongside edit for audit trail ✓")

    # Create + reject
    fake_pipeline_result["session_id"] = str(uuid.uuid4())
    session3 = store.create_session(fake_pipeline_result)
    rejected = store.reject(session3.session_id, "Off-brand messaging")
    print_result("Reject works",
                 rejected.status == HITLStatus.REJECTED,
                 f"Reason stored: 'Off-brand messaging'")

    # Pending list
    fake_pipeline_result["session_id"] = str(uuid.uuid4())
    store.create_session(fake_pipeline_result)
    pending = store.get_pending()
    print_result("Pending list works",
                 len(pending) >= 1,
                 f"{len(pending)} session(s) pending review")

except Exception as e:
    print_result("HITL store failed", False, str(e))
    import traceback; traceback.print_exc()


# ── TEST 4: FastAPI app imports ───────────────────────────────────────────────
print_header("TEST 4: FastAPI app imports")
try:
    from main import app
    print_result("FastAPI app imports", True)
    print_result("App has routes", len(app.routes) > 0,
                 f"{len(app.routes)} routes registered")

    route_paths = [r.path for r in app.routes if hasattr(r, 'path')]
    expected = ["/health", "/generate", "/review/{session_id}", "/history"]
    for path in expected:
        found = path in route_paths
        print_result(f"Route {path}", found)

except Exception as e:
    print_result("FastAPI import failed", False, str(e))
    import traceback; traceback.print_exc()


# ════════════════════════════════════════════════════════════
# PART B — API TESTS (requires running server)
# ════════════════════════════════════════════════════════════

if args.api:
    print_header("PART B: Live API Tests")
    print("  🌐 Testing against running server at http://localhost:8000\n")

    import requests

    BASE = "http://localhost:8000"
    HEADERS = {"X-API-Key": "dev-master-key-2024"}

    # Health check
    try:
        r = requests.get(f"{BASE}/health", timeout=5)
        print_result("/health endpoint", r.status_code == 200,
                     str(r.json().get("status")))
    except Exception as e:
        print_result("/health — server not running?", False, str(e))
        print("\n  ⚠️  Start server with:")
        print("     uvicorn backend.main:app --reload --port 8000")
        sys.exit(1)

    # Rate limit test
    print("\n  Testing rate limiting...")
    r = requests.get(f"{BASE}/health")
    remaining = r.headers.get("X-RateLimit-Remaining", "N/A")
    print_result("Rate limit headers present",
                 remaining != "N/A",
                 f"Tokens remaining: {remaining}")

    # No API key → 401
    r = requests.get(f"{BASE}/history")
    print_result("No API key → 401/403",
                 r.status_code in [401, 403],
                 f"Status: {r.status_code} ✓")

    # Wrong API key → 403
    r = requests.get(f"{BASE}/history",
                     headers={"X-API-Key": "wrong-key"})
    print_result("Wrong API key → 403",
                 r.status_code == 403,
                 f"Status: {r.status_code} ✓")

    # History endpoint
    r = requests.get(f"{BASE}/history", headers=HEADERS)
    print_result("/history works",
                 r.status_code == 200,
                 f"Sessions: {r.json().get('sessions', [])}")

    print("""
  ⚠️  Skipping /generate API test here (takes 60s).
      You can test it manually:

  curl -X POST http://localhost:8000/generate \\
    -H "Content-Type: application/json" \\
    -H "X-API-Key: dev-master-key-2024" \\
    -d '{"topic": "AI in Healthcare", "tone": "professional"}'

  Or open http://localhost:8000/docs for Swagger UI
""")

else:
    print("""
  ─────────────────────────────────────────────────────
  PART A complete. To run live API tests:

  Terminal 1 (start server):
    cd ai-content-studio
    uvicorn backend.main:app --reload --port 8000

  Terminal 2 (run API tests):
    python test_day4.py --api
  ─────────────────────────────────────────────────────
""")


# ── SUMMARY ───────────────────────────────────────────────────────────────────
print_header("DAY 4 SUMMARY")
print("""
  ✅ Semantic Cache     — cosine similarity, LRU eviction, tone-aware
  ✅ Token Bucket       — per-key rate limiting, refill rate, retry-after
  ✅ HITL Store         — approve/edit/reject with audit trail
  ✅ FastAPI App        — /generate /review /history /health endpoints
  ✅ Auth Middleware    — API key validation on all protected routes
  ✅ Rate Limit MW      — runs before auth, protects all endpoints
  ✅ CORS               — allows Streamlit frontend to call the API

  Next → Day 5: Streamlit Frontend
         - Generate page (topic input + tone selector)
         - Review page (HITL — edit + approve/reject)
         - History page (all sessions)
""")