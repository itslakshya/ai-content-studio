# backend/publishing/publisher.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from typing import Optional
from publishing.registry import get_publisher
from publishing.base import PlatformContent
from publishing.image_generator import generate_all_images, generate_image
from publishing.guardrails import check_content_safety


async def publish_approved_content(
    session_data: dict,
    platforms: list,
    generate_images: bool = True,
    linkedin_token: Optional[str] = None,
) -> dict:
    topic = session_data.get("topic", "AI Content")

    print(f"\n{'='*50}")
    print(f"🚀 PUBLISHING: '{topic}'")
    print(f"   Platforms: {platforms}")
    print(f"{'='*50}")

    results = {"overall_success": False, "published_to": [], "images": {}, "safety": {}}

    # ── Content safety check ──────────────────────────────────────────────────
    clean_platforms = []
    for platform in platforms:
        field_map = {
            "twitter":  "twitter_thread",
            "linkedin": "linkedin_post",
            "blog":     "blog_post",
            "bluesky":  "bluesky_post",
        }
        field = field_map.get(platform, "blog_post")
        content = session_data.get(field, "")
        if isinstance(content, list):
            content = " ".join(content)
        safety = await check_content_safety(content, platform)
        results["safety"][platform] = {
            "level": safety.level.value,
            "passed": safety.is_allowed,
        }
        if safety.is_allowed:
            clean_platforms.append(platform)
        else:
            results[platform] = {
                "success": False,
                "error": f"Content failed safety check: {safety.reason}",
            }

    if not clean_platforms:
        results["error"] = "All platforms failed safety checks"
        return results

    # ── Resolve images ────────────────────────────────────────────────────────
    # CRITICAL: reuse the SAME cover image the user saw in preview/review. It's
    # cached in the DB (cover_image_url), generated once at blog dimensions.
    # Regenerating here would produce a DIFFERENT image (different dims/seed),
    # which is exactly the bug we're fixing. So we fetch the stored URL and use
    # it for every platform.
    images = {}
    if generate_images:
        from database.repositories import SessionRepository
        _repo = SessionRepository()
        _sid  = session_data.get("session_id")
        cover = _repo.get_cover_image(_sid) if _sid else ""

        if not cover:
            # No cached image yet (e.g. user published without opening preview).
            # Generate once now and persist so it's stable from here on.
            cover = await generate_image(
                topic=topic, platform="blog", session_id=_sid,
            )
            if _sid and cover:
                _repo.set_cover_image(_sid, cover)

        # Use the same cover image for every platform being published
        images = {p: cover for p in clean_platforms}
        results["images"] = images

    # ── Publish concurrently ──────────────────────────────────────────────────
    async def publish_one(platform: str):
        try:
            publisher = get_publisher(platform)

            # Get bluesky_post with fallback to linkedin_post
            bluesky_content = session_data.get("bluesky_post", "")
            if not bluesky_content:
                li = session_data.get("linkedin_post", "")
                bluesky_content = (li[:280] + "…") if len(li) > 280 else li

            # Get telegram_post with fallback to bluesky
            telegram_content = session_data.get("telegram_post", "")
            if not telegram_content:
                bsky = session_data.get("bluesky_post", "")
                telegram_content = bsky[:1020] if bsky else ""

            content = PlatformContent(
                topic=topic,
                tone=session_data.get("tone", "professional"),
                blog_post=session_data.get("blog_post", ""),
                linkedin_post=session_data.get("linkedin_post", ""),
                twitter_thread=session_data.get("twitter_thread", []),
                bluesky_post=bluesky_content,
                telegram_post=telegram_content,
                image_path=images.get(platform),
            )
            return platform, await publisher.run(content)
        except Exception as e:
            from publishing.base import PublishResult
            return platform, PublishResult(
                platform=platform, success=False, error=str(e)
            )

    tasks = [publish_one(p) for p in clean_platforms]
    publish_results = await asyncio.gather(*tasks, return_exceptions=True)

    for item in publish_results:
        if isinstance(item, Exception):
            continue
        platform, result = item
        results[platform] = result.to_dict() if hasattr(result, "to_dict") else {"success": False}
        if result.success:
            results["published_to"].append(platform)

    results["overall_success"] = len(results["published_to"]) > 0

    print(f"\n📊 Publishing summary:")
    print(f"   ✅ Succeeded: {results['published_to']}")
    failed = [p for p in clean_platforms if p not in results["published_to"]]
    if failed:
        print(f"   ❌ Failed: {failed}")

    return results