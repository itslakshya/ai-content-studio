# backend/security/auth.py
# ─────────────────────────────────────────────────────────────────────────────
# API key authentication for FastAPI.
# Simple but production-pattern: key in header, validated against known keys.
# ─────────────────────────────────────────────────────────────────────────────

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
from config import get_settings

settings = get_settings()
api_key_header = APIKeyHeader(name=settings.api_key_header, auto_error=False)


async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """
    FastAPI dependency that validates the API key from request headers.

    Usage in route:
        @app.post("/generate")
        async def generate(api_key: str = Depends(verify_api_key)):
            ...

    INTERVIEW: "How did you secure your API?"
    ANSWER: "API key authentication via custom header (X-API-Key).
    Keys are validated server-side. In production I'd add key rotation,
    per-key permissions, and store keys hashed in a database. For this
    project, the master key is in .env and never committed to git."
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required. Add X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Validate against master key (in production: check database)
    if api_key != settings.master_api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )

    return api_key