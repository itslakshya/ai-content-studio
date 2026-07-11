# backend/publishing/platforms/linkedin.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import httpx
from publishing.base import BasePlatformPublisher, PlatformContent, PublishResult
from config import get_settings


class LinkedInPublisher(BasePlatformPublisher):
    platform_name = "linkedin"
    platform_display = "LinkedIn"
    platform_emoji = "💼"
    content_field = "linkedin_post"
    max_content_length = 1900
    supports_images = True
    image_aspect_ratio = "1:1"

    async def validate_credentials(self) -> tuple[bool, str]:
        s = get_settings()
        if not s.linkedin_client_id or s.linkedin_client_id.startswith("your_"):
            return False, "Missing LINKEDIN_CLIENT_ID. Add to .env"
        if not s.linkedin_access_token or s.linkedin_access_token.startswith("your_"):
            return False, "Missing LINKEDIN_ACCESS_TOKEN. Visit /linkedin/auth-url to connect"
        return True, "Ready"

    async def format_content(self, content: PlatformContent) -> PlatformContent:
        """Truncate if over LinkedIn limit."""
        if len(content.linkedin_post) > self.max_content_length:
            content.linkedin_post = content.linkedin_post[:self.max_content_length - 3] + "..."
        return content

    async def publish(self, content: PlatformContent) -> PublishResult:
        if not content.linkedin_post:
            return PublishResult(platform=self.platform_name, success=False,
                                 error="No LinkedIn post content")
        s = get_settings()
        token = s.linkedin_access_token
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                me = await client.get("https://api.linkedin.com/v2/me",
                                       headers={"Authorization": f"Bearer {token}"})
                if me.status_code != 200:
                    return PublishResult(platform=self.platform_name, success=False,
                                         error="LinkedIn token invalid or expired")
                user_id = me.json().get("id")
                author_urn = f"urn:li:person:{user_id}"

            image_asset = None
            if content.image_path and os.path.exists(content.image_path):
                image_asset = await self._upload_image(token, author_urn, content.image_path)

            payload = {
                "author": author_urn,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": content.linkedin_post},
                        "shareMediaCategory": "IMAGE" if image_asset else "NONE",
                    }
                },
                "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
            }
            if image_asset:
                payload["specificContent"]["com.linkedin.ugc.ShareContent"]["media"] = [{
                    "status": "READY",
                    "description": {"text": "AI Content Studio"},
                    "media": image_asset,
                    "title": {"text": content.topic},
                }]

            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    "https://api.linkedin.com/v2/ugcPosts",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}",
                             "Content-Type": "application/json",
                             "X-Restli-Protocol-Version": "2.0.0"},
                )
            if r.status_code == 201:
                post_id = r.headers.get("x-restli-id", "unknown")
                return PublishResult(platform=self.platform_name, success=True,
                                     url="https://www.linkedin.com/feed/",
                                     post_id=post_id,
                                     image_path=content.image_path or "")
            return PublishResult(platform=self.platform_name, success=False,
                                 error=f"HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            return PublishResult(platform=self.platform_name, success=False, error=str(e))

    async def _upload_image(self, token, author_urn, image_path) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    "https://api.linkedin.com/v2/assets?action=registerUpload",
                    json={"registerUploadRequest": {
                        "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                        "owner": author_urn,
                        "serviceRelationships": [{"relationshipType": "OWNER",
                                                   "identifier": "urn:li:userGeneratedContent"}]
                    }},
                    headers={"Authorization": f"Bearer {token}",
                             "Content-Type": "application/json"},
                )
                if r.status_code != 200:
                    return None
                data = r.json()
                upload_url = data["value"]["uploadMechanism"][
                    "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
                asset_urn = data["value"]["asset"]
                with open(image_path, "rb") as f:
                    await client.put(upload_url, content=f.read(),
                                     headers={"Authorization": f"Bearer {token}"})
                return asset_urn
        except Exception:
            return None