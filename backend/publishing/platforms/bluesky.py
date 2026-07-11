# backend/publishing/platforms/bluesky.py
# AT Protocol publishing — free, instant setup
# Setup: bsky.app → Settings → Privacy → App Passwords → Add App Password

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import httpx
import datetime
from typing import Optional
from publishing.base import BasePlatformPublisher, PlatformContent, PublishResult
from config import get_settings


class BlueskyPublisher(BasePlatformPublisher):
    platform_name    = "bluesky"
    platform_display = "Bluesky"
    platform_emoji   = "☁️"
    content_field    = "bluesky_post"   # Uses dedicated bluesky_post field
    max_content_length = 300
    supports_images  = True
    image_aspect_ratio = "16:9"
    BASE = "https://bsky.social/xrpc"

    async def validate_credentials(self) -> tuple[bool, str]:
        s = get_settings()
        if not s.bluesky_handle:
            return False, "Missing BLUESKY_HANDLE (e.g. yourname.bsky.social)"
        if not s.bluesky_app_password:
            return False, "Missing BLUESKY_APP_PASSWORD — create at bsky.app → Settings → App Passwords"
        return True, "Ready"

    async def _auth(self) -> tuple[Optional[str], Optional[str]]:
        """Get session token. Returns (accessJwt, did)."""
        s = get_settings()
        handle = s.bluesky_handle.lstrip("@")
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(
                    f"{self.BASE}/com.atproto.server.createSession",
                    json={"identifier": handle, "password": s.bluesky_app_password},
                    headers={"Content-Type": "application/json"},
                )
                if r.status_code == 200:
                    d = r.json()
                    print(f"   ✅ Bluesky auth: @{d.get('handle','?')}")
                    return d.get("accessJwt"), d.get("did")
                print(f"   ❌ Bluesky auth HTTP {r.status_code}: {r.text[:150]}")
        except Exception as e:
            print(f"   ❌ Bluesky auth error: {e}")
        return None, None

    async def _upload_image(self, token: str, image_url: str) -> Optional[dict]:
        """Download image URL then upload blob to Bluesky."""
        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=True) as c:
                img = await c.get(image_url)
                if img.status_code != 200:
                    print(f"   ⚠️  Image download failed: {img.status_code}")
                    return None
                if len(img.content) < 1000:
                    print(f"   ⚠️  Image too small: {len(img.content)} bytes")
                    return None
                ct = img.headers.get("content-type", "image/jpeg")
                if "image" not in ct:
                    ct = "image/jpeg"
                r = await c.post(
                    f"{self.BASE}/com.atproto.repo.uploadBlob",
                    content=img.content,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": ct},
                )
                if r.status_code == 200:
                    print(f"   ✅ Bluesky image uploaded ({len(img.content)//1024}KB)")
                    return r.json().get("blob")
                print(f"   ⚠️  Blob upload HTTP {r.status_code}: {r.text[:100]}")
        except Exception as e:
            print(f"   ⚠️  Image upload error: {e}")
        return None

    async def format_content(self, content: PlatformContent) -> PlatformContent:
        """Use bluesky_post if available, fall back to truncated linkedin_post."""
        import re
        if content.bluesky_post and len(content.bluesky_post.strip()) > 10:
            text = content.bluesky_post.strip()
        else:
            li = content.linkedin_post or ""
            text = (li[:277] + "…") if len(li) > 280 else li

        # CRITICAL: Bluesky is PLAIN TEXT — strip all markdown formatting
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)   # **bold** → bold
        text = re.sub(r'\*(.+?)\*', r'\1', text)       # *italic* → italic
        text = re.sub(r'__(.+?)__', r'\1', text)          # __bold__ → bold
        text = re.sub(r'_(.+?)_', r'\1', text)            # _italic_ → italic
        text = text.replace('#', '')                        # Remove stray # headers
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)  # [link](url) → link

        # Clean up extra whitespace
        text = re.sub(r'  +', ' ', text).strip()

        # Ensure under 300 chars
        if len(text) > 295:
            text = text[:292] + "…"
        content.bluesky_post = text
        return content

    async def publish(self, content: PlatformContent) -> PublishResult:
        post_text = content.bluesky_post
        if not post_text or not post_text.strip():
            # Last resort fallback
            li = content.linkedin_post or ""
            post_text = (li[:277] + "…") if len(li) > 277 else li
            if not post_text:
                return PublishResult(platform=self.platform_name, success=False,
                                     error="No post content available")

        print(f"   📝 Bluesky post ({len(post_text)} chars): {post_text[:60]}…")

        token, did = await self._auth()
        if not token or not did:
            return PublishResult(
                platform=self.platform_name, success=False,
                error=(
                    "Bluesky authentication failed. "
                    "Check BLUESKY_HANDLE (e.g. name.bsky.social) and "
                    "BLUESKY_APP_PASSWORD (create at bsky.app → Settings → App Passwords)"
                ),
            )

        try:
            record: dict = {
                "$type":     "app.bsky.feed.post",
                "text":      post_text[:300],
                "createdAt": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "langs":     ["en"],
            }

            # Attach image if available
            image_url = content.image_path
            if image_url and isinstance(image_url, str) and image_url.startswith("http"):
                blob = await self._upload_image(token, image_url)
                if blob:
                    record["embed"] = {
                        "$type":  "app.bsky.embed.images",
                        "images": [{
                            "image": blob,
                            "alt":   content.topic[:100],
                        }],
                    }

            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post(
                    f"{self.BASE}/com.atproto.repo.createRecord",
                    json={
                        "repo":       did,
                        "collection": "app.bsky.feed.post",
                        "record":     record,
                    },
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type":  "application/json",
                    },
                )

            print(f"   📡 Bluesky createRecord: HTTP {r.status_code}")

            if r.status_code == 200:
                data = r.json()
                uri  = data.get("uri", "")
                rkey = uri.split("/")[-1] if "/" in uri else ""
                s = get_settings()
                handle = s.bluesky_handle.lstrip("@")
                url = f"https://bsky.app/profile/{handle}/post/{rkey}" if rkey else "https://bsky.app"
                print(f"   ✅ Bluesky published: {url}")
                return PublishResult(
                    platform=self.platform_name, success=True,
                    url=url, post_id=rkey,
                    image_path=image_url or "",
                )

            # Show full error for debugging
            print(f"   ❌ Bluesky response: {r.text[:300]}")
            return PublishResult(
                platform=self.platform_name, success=False,
                error=f"HTTP {r.status_code}: {r.text[:200]}",
            )

        except Exception as e:
            print(f"   ❌ Bluesky publish exception: {e}")
            return PublishResult(platform=self.platform_name, success=False, error=str(e))