# backend/main.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uuid, time, asyncio
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from config import get_settings, validate_settings
from agents.graph import run_pipeline, get_graph
from cache.semantic_cache import get_cache
from security.rate_limiter import get_rate_limiter
from security.auth import verify_api_key
from hitl.review import get_hitl_store
from database.db import init_db
from observability.tracker import get_tracker


# ── Request/Response Models ───────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    topic: str = Field(..., min_length=3, max_length=300)
    tone: str = Field(default="professional")
    platforms: List[str] = Field(default=["blog", "linkedin", "twitter"])
    additional_context: Optional[str] = Field(default=None, max_length=500)

    @field_validator("tone")
    @classmethod
    def validate_tone(cls, v):
        valid = ["professional","casual","witty","educational","inspirational","conversational"]
        return v.lower() if v.lower() in valid else "professional"

    @field_validator("platforms")
    @classmethod
    def validate_platforms(cls, v):
        valid = {"blog","linkedin","twitter","bluesky","telegram"}
        return [p.lower() for p in v if p.lower() in valid]


class GenerateResponse(BaseModel):
    session_id: str
    status: str
    topic: str
    tone: str
    critique_score: float
    rewrite_count: int
    blog_post: Optional[str] = None
    linkedin_post: Optional[str] = None
    twitter_thread: Optional[List[str]] = None
    bluesky_post: Optional[str] = None
    telegram_post: Optional[str] = None
    blog_word_count: int
    linkedin_char_count: int
    twitter_tweet_count: int
    sources: List[str]
    elapsed_seconds: float
    cached: bool = False
    hitl_status: str = "pending"

    model_config = {"extra": "ignore"}  # ignore any unexpected fields


class ReviewAction(BaseModel):
    action: str = Field(...)
    reviewer_notes: Optional[str] = Field(default="")
    blog_post: Optional[str] = None
    linkedin_post: Optional[str] = None
    twitter_thread: Optional[List[str]] = None
    bluesky_post: Optional[str] = None
    telegram_post: Optional[str] = None

    @field_validator("action")
    @classmethod
    def validate_action(cls, v):
        if v not in ["approve","reject","edit","reopen"]:
            raise ValueError("action must be: approve, reject, edit, or reopen")
        return v


class PublishRequest(BaseModel):
    session_id: str
    platforms: List[str] = Field(default=["blog","bluesky","telegram"])
    generate_images: bool = Field(default=True)
    linkedin_token: Optional[str] = Field(default=None)

    @field_validator("platforms")
    @classmethod
    def validate_platforms(cls, v):
        valid = {"twitter","linkedin","blog","bluesky","telegram"}
        return [p for p in v if p in valid]


class SafetyCheckRequest(BaseModel):
    topic: str


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n" + "="*60)
    print("  🚀 AI Content Studio — Starting up")
    print("="*60)

    # ── Security gate: refuse to start with insecure defaults ────────────────
    _key = get_settings().master_api_key
    if not _key:
        print("⚠️  WARNING: MASTER_API_KEY is empty — API endpoints will reject requests.")
        print("   Set it in your environment variables or .env file.")
    elif _key in ("dev-master-key-2024", "change-this-in-production"):
        import os
        _env = os.getenv("ENVIRONMENT", "development")
        if _env != "development":
            print("=" * 60)
            print("  ⚠️  SECURITY WARNING")
            print("  MASTER_API_KEY is using an insecure default value.")
            print("  Generate a secure key and update your environment:")
            print('  python -c "import secrets; print(secrets.token_hex(32))"')
            print("=" * 60)
        else:
            print("⚠️  WARNING: Using dev API key. Set MASTER_API_KEY before deployment.")

    init_db()  # SQLite + WAL mode

    # Clean up orphaned 'running' pipeline runs from prior crashes/interrupts
    # so the observability dashboard shows accurate stats.
    try:
        from database.repositories import MetricsRepository
        n_cleaned = MetricsRepository().cleanup_orphaned_runs(older_than_seconds=300)
        if n_cleaned:
            print(f"🧹 Cleaned up {n_cleaned} orphaned pipeline run(s)")
    except Exception as e:
        print(f"⚠️  Orphaned-run cleanup skipped: {e}")

    if not validate_settings():
        raise RuntimeError("Missing required API keys")

    print("🔄 Pre-compiling LangGraph graph...")
    get_graph()

    print("🔄 Warming up embedding model...")
    try:
        from rag.embeddings import embed_single
        embed_single("warmup")
        print("✅ Embedding model warm")
    except Exception as e:
        print(f"⚠️  Embedding warmup failed: {e}")

    print("🔄 Loading vector store and seeding knowledge base...")
    try:
        from rag.vectorstore import get_vector_store
        from rag.seeder import seed_knowledge_base
        store = get_vector_store()
        seeded = await seed_knowledge_base()
        print(f"✅ Vector store ready: {store.total_chunks} chunks ({seeded} newly added)")
    except Exception as e:
        print(f"⚠️  Vector store init failed: {e}")

    settings = get_settings()
    print(f"\n✅ Server ready on {settings.backend_url}")
    print(f"   Model : {settings.groq_model}")
    print("="*60 + "\n")

    yield
    print("\n🛑 Shutting down...")


# ── App ───────────────────────────────────────────────────────────────────────
settings = get_settings()
app = FastAPI(
    title="AI Content Studio",
    description="Multi-agent AI content generation with HITL review and auto-publishing",
    version=settings.app_version,
    lifespan=lifespan,
)


@app.get("/", include_in_schema=False)
async def root():
    """Root URL — confirms the API is running."""
    return {
        "app": "AI Content Studio",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
    }

# CORS — restrict to configured origins.
# In .env: ALLOWED_ORIGINS=https://myapp.hf.space,http://localhost:8501
# Never use ["*"] in production — it allows any website to call your API.
_allowed_origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ── Rate limiting middleware ──────────────────────────────────────────────────
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    start = time.time()
    if request.url.path in ["/health", "/docs", "/redoc", "/openapi.json"]:
        return await call_next(request)

    api_key = request.headers.get(settings.api_key_header, "anonymous")
    limiter = get_rate_limiter()
    rate_result = limiter.check(api_key)

    if not rate_result["allowed"]:
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit exceeded",
                     "retry_after_seconds": rate_result["retry_after"]},
            headers={"Retry-After": str(rate_result["retry_after"])},
        )

    response = await call_next(request)
    response.headers["X-RateLimit-Remaining"] = str(rate_result["tokens_remaining"])
    response.headers["X-Request-Time"] = f"{(time.time()-start):.3f}s"
    return response


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health_check():
    store = None
    try:
        from rag.vectorstore import get_vector_store
        store = get_vector_store()
    except Exception:
        pass
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
        "model": settings.groq_model,
        "vector_store_chunks": store.total_chunks if store else 0,
        "cache_stats": get_cache().get_stats(),
        "publishing": settings.publishing_configured(),
    }


@app.post("/safety/check", tags=["Safety"])
async def safety_check(request: SafetyCheckRequest):
    """Pre-check topic safety before running the pipeline."""
    from publishing.guardrails import check_topic_safety
    result = await check_topic_safety(request.topic)
    return {
        "level": result.level.value,
        "is_allowed": result.is_allowed,
        "reason": result.reason,
        "warning_message": result.warning_message,
    }


@app.get("/platforms", tags=["Platforms"])
async def list_platforms(api_key: str = Depends(verify_api_key)):
    from publishing.registry import get_available_platforms
    return {"platforms": get_available_platforms()}


@app.get("/platforms/status", tags=["Platforms"])
async def platform_status(api_key: str = Depends(verify_api_key)):
    from publishing.registry import get_platform_status
    statuses = await get_platform_status()
    return {
        "platforms": statuses,
        "ready": [s["id"] for s in statuses if s["configured"]],
        "not_configured": [s["id"] for s in statuses if not s["configured"]],
    }



@app.get("/preview-image")
async def get_preview_image(topic: str, platform: str = "blog", session_id: str = ""):
    """
    Returns the cover image URL for a session's content.

    STABILITY GUARANTEE: the image is generated exactly ONCE per session and
    cached in the database (cover_image_url). Every subsequent call — generate
    screen, review screen, publish — returns that same stored URL. This is what
    makes the image identical across the entire lifecycle and across restarts.

    Without a session_id (rare), a one-off image is generated and not cached.
    """
    from publishing.image_generator import generate_image
    from database.repositories import SessionRepository

    repo = SessionRepository()

    # 1. If we already generated & stored an image for this session, reuse it.
    if session_id:
        existing = repo.get_cover_image(session_id)
        if existing:
            return {"url": existing, "topic": topic, "platform": platform, "cached": True}

    # 2. Otherwise generate it ONCE (always at blog dimensions for consistency)
    try:
        url = await generate_image(
            topic=topic, platform="blog",   # fixed dims → consistent render
            session_id=session_id or None,
        )
    except Exception:
        import hashlib
        seed = int(hashlib.md5((session_id or topic).encode()).hexdigest(), 16) % 1000
        url = f"https://picsum.photos/seed/{seed}/800/420"

    # 3. Persist it so all future calls (and publish) reuse the exact same URL
    if session_id and url:
        try:
            repo.set_cover_image(session_id, url)
        except Exception as e:
            print(f"⚠️  Could not cache cover image: {e}")

    return {"url": url or "", "topic": topic, "platform": platform, "cached": False}


@app.post("/generate", response_model=GenerateResponse, tags=["Content"])
async def generate_content(
    request: GenerateRequest,
    api_key: str = Depends(verify_api_key),
):
    start_time = time.time()
    session_id = str(uuid.uuid4())
    tracker = get_tracker()

    # Safety check first
    from publishing.guardrails import check_topic_safety
    safety = await check_topic_safety(request.topic)
    if not safety.is_allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Topic blocked by safety guardrails: {safety.reason}",
        )

    # Check semantic cache
    cache = get_cache()
    cache_query = f"{request.topic} {' '.join(request.platforms)}"
    cached_result = cache.get(cache_query, tone=request.tone)

    if cached_result:
        elapsed = time.time() - start_time
        hitl_store = get_hitl_store()
        # Copy so we don't mutate the shared cache entry (which would corrupt
        # future cache hits and break reject-invalidation matching by topic).
        import copy as _copy
        cached_result = _copy.deepcopy(cached_result)
        cached_result["session_id"] = session_id
        hitl_store.create_session(cached_result)
        _run_id = tracker.start_run(session_id, request.topic)
        tracker.end_run(_run_id, status="complete", cached=True)
        return GenerateResponse(
            session_id=session_id, status="success",
            topic=request.topic, tone=request.tone,
            critique_score=cached_result.get("critique_score", 0),
            rewrite_count=cached_result.get("rewrite_count", 0),
            blog_post=cached_result.get("blog_post"),
            linkedin_post=cached_result.get("linkedin_post"),
            twitter_thread=cached_result.get("twitter_thread"),
            bluesky_post=cached_result.get("bluesky_post"),
            telegram_post=cached_result.get("telegram_post"),
            blog_word_count=cached_result.get("blog_word_count", 0),
            linkedin_char_count=cached_result.get("linkedin_char_count", 0),
            twitter_tweet_count=cached_result.get("twitter_tweet_count", 0),
            sources=cached_result.get("sources", []),
            elapsed_seconds=round(elapsed, 2),
            cached=True,
            hitl_status="pending",
        )

    # Pre-create session row (needed so tracker.start_run can reference it)
    # Even though FK is removed in v3, this is the cleaner ordering
    hitl_store = get_hitl_store()
    hitl_store.create_session({
        "session_id": session_id,
        "topic":      request.topic,
        "tone":       request.tone,
        "target_platforms": request.platforms,
    })

    # Run full pipeline
    _run_id = tracker.start_run(session_id, request.topic)
    try:
        final_state = await run_pipeline(
            topic=request.topic,
            tone=request.tone,
            target_platforms=request.platforms,
            session_id=session_id,
            additional_context=request.additional_context,
        )
    except Exception as e:
        tracker.end_run(_run_id, status="error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {str(e)}")

    elapsed = time.time() - start_time

    if final_state.get("error"):
        tracker.end_run(_run_id, status="error", error=final_state.get("error",""))
        raise HTTPException(status_code=422, detail=final_state["error"])

    # Use REAL token counts captured from Groq's usage_metadata (not estimates)
    _real_in  = final_state.get("total_input_tokens", 0)
    _real_out = final_state.get("total_output_tokens", 0)
    _real_total = _real_in + _real_out
    _agent_metrics = final_state.get("agent_metrics", [])

    tracker.end_run(
        _run_id,
        total_latency_s=elapsed,
        critique_score=final_state.get("critique_score", 0),
        rewrite_count=final_state.get("rewrite_count", 0),
        total_tokens=_real_total,        # REAL tokens from API, 0 → tracker estimates
        input_tokens=_real_in,
        output_tokens=_real_out,
        agent_metrics=_agent_metrics,    # per-agent latency + tokens
        blog_post=final_state.get("blog_post", ""),
        linkedin_post=final_state.get("linkedin_post", ""),
        twitter_thread=final_state.get("twitter_thread", []),
        bluesky_post=final_state.get("bluesky_post", ""),
        telegram_post=final_state.get("telegram_post", ""),
    )
    print(f"📊 Run tokens (real): {_real_in} in + {_real_out} out = {_real_total}")

    hitl_store = get_hitl_store()
    result_dict = dict(final_state)
    result_dict["session_id"] = session_id
    hitl_store.create_session(result_dict)
    cache.set(cache_query, request.tone, result_dict, request.topic)

    return GenerateResponse(
        session_id=session_id, status="success",
        topic=request.topic, tone=request.tone,
        critique_score=final_state.get("critique_score", 0),
        rewrite_count=final_state.get("rewrite_count", 0),
        blog_post=final_state.get("blog_post"),
        linkedin_post=final_state.get("linkedin_post"),
        twitter_thread=final_state.get("twitter_thread"),
        bluesky_post=final_state.get("bluesky_post"),
        telegram_post=final_state.get("telegram_post"),
        blog_word_count=final_state.get("blog_word_count", 0),
        linkedin_char_count=final_state.get("linkedin_char_count", 0),
        twitter_tweet_count=final_state.get("twitter_tweet_count", 0),
        sources=final_state.get("sources", []),
        elapsed_seconds=round(elapsed, 2),
        cached=False,
        hitl_status="pending",
    )


@app.post("/review/{session_id}", tags=["HITL"])
async def review_content(
    session_id: str,
    action: ReviewAction,
    api_key: str = Depends(verify_api_key),
):
    hitl_store = get_hitl_store()
    if action.action == "approve":
        session = hitl_store.approve(session_id, action.reviewer_notes or "")
    elif action.action == "reject":
        session = hitl_store.reject(session_id, action.reviewer_notes or "")
        # Invalidate cache so re-generating the same topic gives FRESH content
        # (not the rejected version). Try session_id first, then topic+tone.
        if session:
            cache = get_cache()
            if not cache.invalidate_by_session(session_id):
                cache.invalidate_by_topic(
                    session.get("topic", ""), session.get("tone", "")
                )
    elif action.action == "reopen":
        session = hitl_store.reopen(session_id)
    elif action.action == "edit":
        session = hitl_store.edit_and_approve(
            session_id=session_id,
            blog_post=action.blog_post,
            linkedin_post=action.linkedin_post,
            twitter_thread=action.twitter_thread,
            bluesky_post=action.bluesky_post,
            telegram_post=action.telegram_post,
            reviewer_notes=action.reviewer_notes or "",
        )
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return {
        "session_id": session_id,
        "status": session.get("status", "pending"),
        "message": f"Content {session.get('status', 'pending')} successfully",
        "reviewed_at": session.get("reviewed_at"),
        "edits_made": len(session.get("human_edits", {})),
    }


@app.get("/review/pending", tags=["HITL"])
async def get_pending_reviews(api_key: str = Depends(verify_api_key)):
    hitl_store = get_hitl_store()
    pending = hitl_store.get_pending()
    return {"count": len(pending), "sessions": pending}


@app.get("/review/{session_id}", tags=["HITL"])
async def get_session(session_id: str, api_key: str = Depends(verify_api_key)):
    hitl_store = get_hitl_store()
    session = hitl_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return session


@app.get("/history", tags=["HITL"])
async def get_history(api_key: str = Depends(verify_api_key)):
    hitl_store = get_hitl_store()
    return {"sessions": hitl_store.get_all(), "cache_stats": get_cache().get_stats()}


@app.post("/publish/{session_id}", tags=["Publishing"])
async def publish_content(
    session_id: str,
    request: PublishRequest,
    api_key: str = Depends(verify_api_key),
):
    from publishing.publisher import publish_approved_content
    hitl_store = get_hitl_store()
    session = hitl_store.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    if session.get("status", "pending") not in ["approved","edited"]:
        raise HTTPException(
            status_code=400,
            detail=f"Content must be approved first. Current: {session.get('status', 'pending')}",
        )

    try:
        results = await publish_approved_content(
            session_data=session,
            platforms=request.platforms,
            generate_images=request.generate_images,
            linkedin_token=request.linkedin_token,
        )
        # Record per-platform publish status in HITL session
        _store = get_hitl_store()
        for _platform in results.get("published_to", []):
            _url = results.get(_platform, {}).get("url", f"published:{_platform}")
            _store.record_publish(session_id, _platform, _url)

        return {
            "session_id": session_id,
            "topic": session.get("topic", ""),
            "publishing_results": results,
            "published_to": results.get("published_to", []),
            "overall_success": results.get("overall_success", False),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Publishing failed: {str(e)}")


@app.post("/reject-platform/{session_id}/{platform}", tags=["Publishing"])
async def reject_platform(
    session_id: str,
    platform: str,
    api_key: str = Depends(verify_api_key),
):
    """
    Reject a SINGLE platform for a session (not the whole session).
    Records it in the publishes table with success=0 so the history page
    shows it as 'rejected' for that platform only.
    """
    from database.repositories import PublishRepository
    hitl_store = get_hitl_store()
    session = hitl_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    valid_platforms = {"blog", "bluesky", "telegram", "twitter", "linkedin"}
    if platform not in valid_platforms:
        raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")

    PublishRepository().record_rejection(session_id, platform)
    return {
        "session_id": session_id,
        "platform": platform,
        "state": "rejected",
        "message": f"{platform} rejected for this session",
    }


@app.get("/platform-states/{session_id}", tags=["Publishing"])
async def platform_states(
    session_id: str,
    api_key: str = Depends(verify_api_key),
):
    """Return per-platform state (published/rejected/unpublished) for a session."""
    from database.repositories import PublishRepository
    states = PublishRepository().get_all_platform_states(session_id)
    return {"session_id": session_id, "states": states}


@app.get("/linkedin/auth-url", tags=["Publishing"])
async def get_linkedin_auth_url(
    redirect_uri: str = "http://localhost:8000/linkedin/callback",
    api_key: str = Depends(verify_api_key),
):
    from publishing.linkedin_publisher import get_linkedin_auth_url
    url = get_linkedin_auth_url(redirect_uri)
    return {"auth_url": url, "redirect_uri": redirect_uri}


@app.get("/linkedin/callback", tags=["Publishing"])
async def linkedin_callback(code: str, state: str = ""):
    from publishing.linkedin_publisher import exchange_code_for_token
    token = await exchange_code_for_token(
        code, "http://localhost:8000/linkedin/callback")
    if token:
        return {"success": True, "access_token": token,
                "message": "Add this as LINKEDIN_ACCESS_TOKEN in .env"}
    return {"success": False, "error": "Token exchange failed"}


# ── Observability Routes ──────────────────────────────────────────────────────

@app.get("/observability/summary", tags=["Observability"])
async def obs_summary(api_key: str = Depends(verify_api_key)):
    """Overall pipeline statistics."""
    return get_tracker().get_summary()


@app.get("/observability/runs", tags=["Observability"])
async def obs_runs(api_key: str = Depends(verify_api_key)):
    """All pipeline runs with per-agent breakdown."""
    return {"runs": get_tracker().get_runs()}


@app.get("/observability/runs/{session_id}", tags=["Observability"])
async def obs_run(session_id: str, api_key: str = Depends(verify_api_key)):
    """Single pipeline run detail (by session_id)."""
    runs = get_tracker().get_runs(limit=100)
    match = next((r for r in runs if r.get("session_id") == session_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="Run not found")
    return match


# ── Cache ─────────────────────────────────────────────────────────────────────

@app.get("/cache/stats", tags=["System"])
async def cache_stats(api_key: str = Depends(verify_api_key)):
    return get_cache().get_stats()


@app.delete("/cache", tags=["System"])
async def clear_cache(api_key: str = Depends(verify_api_key)):
    get_cache().clear()
    return {"message": "Cache cleared"}