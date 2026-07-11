# backend/api/platforms.py
# Routes for platform registry — frontend reads this to show platform options.

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, Depends
from security.auth import verify_api_key
from publishing.registry import get_available_platforms, get_platform_status

router = APIRouter(prefix="/platforms", tags=["Platforms"])


@router.get("/")
async def list_platforms(api_key: str = Depends(verify_api_key)):
    """
    Returns all registered platforms with metadata.
    Frontend reads this to dynamically show platform options.
    Adding a new platform to the registry auto-appears here.
    """
    return {"platforms": get_available_platforms()}


@router.get("/status")
async def platform_status(api_key: str = Depends(verify_api_key)):
    """Check which platforms have credentials configured."""
    statuses = await get_platform_status()
    return {
        "platforms": statuses,
        "ready": [s["id"] for s in statuses if s["configured"]],
        "not_configured": [s["id"] for s in statuses if not s["configured"]],
    }