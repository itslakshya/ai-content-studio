# backend/publishing/platforms/devto.py
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import httpx
from datetime import datetime
from publishing.base import BasePlatformPublisher, PlatformContent, PublishResult
from config import get_settings


class DevToPublisher(BasePlatformPublisher):
    platform_name    = "blog"
    platform_display = "Dev.to Blog"
    platform_emoji   = "📝"
    content_field    = "blog_post"
    max_content_length = 100000
    supports_images  = True
    image_aspect_ratio = "16:9"

    async def validate_credentials(self) -> tuple[bool, str]:
        s = get_settings()
        if not s.devto_api_key or s.devto_api_key.startswith("your_"):
            return False, "Missing DEVTO_API_KEY. Get at dev.to/settings/account"
        return True, "Ready"

    async def format_content(self, content: PlatformContent) -> PlatformContent:
        """
        Prepare blog post:
        1. Extract title from first # heading
        2. Attach cover image URL at top
        3. Replace [IMAGE: desc] markers with actual markdown images
        """
        blog = content.blog_post
        lines = blog.split("\n")

        if lines[0].startswith("# "):
            title_line = lines[0]
            body = "\n".join(lines[1:]).strip()
        else:
            title_line = f"# {content.topic}"
            body = blog

        image_url = content.image_path

        # Step 1: Replace [IMAGE: description] markers with real image markdown
        # Uses the cover image URL for all inline images (same contextual image)
        if image_url and isinstance(image_url, str) and image_url.startswith("http"):
            def replace_marker(match):
                desc = match.group(1).strip()[:100]
                return f"\n\n![{desc}]({image_url})\n\n"

            body = re.sub(r'\[IMAGE:([^\]]+)\]', replace_marker, body)
            print(f"   ✅ [IMAGE:] markers replaced with actual image URL")

            # Step 2: Prepend cover image
            body = (
                f"![{content.topic} — cover image]({image_url})\n\n"
                + body
            )
        else:
            # No image — just remove the markers cleanly
            body = re.sub(r'\[IMAGE:[^\]]+\]\n*', '', body)
            print(f"   ⚠️  No image available — [IMAGE:] markers removed")

        content.blog_post = f"{title_line}\n\n{body}"
        return content

    async def publish(self, content: PlatformContent) -> PublishResult:
        if not content.blog_post:
            return PublishResult(platform=self.platform_name, success=False,
                                 error="No blog post content")
        s = get_settings()

        lines = content.blog_post.split("\n")
        title = lines[0].replace("# ", "").strip() if lines[0].startswith("# ") else content.topic
        body  = "\n".join(lines[1:]).strip() if lines[0].startswith("# ") else content.blog_post
        tags  = [w.lower() for w in content.topic.split()
                 if len(w) > 3 and w.isalpha()][:4] or ["ai", "technology"]

        payload: dict = {
            "article": {
                "title": title,
                "body_markdown": body,
                "published": True,
                "tags": tags,
            }
        }
        image_url = content.image_path
        if image_url and isinstance(image_url, str) and image_url.startswith("http"):
            payload["article"]["main_image"] = image_url

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    "https://dev.to/api/articles",
                    json=payload,
                    headers={"api-key": s.devto_api_key,
                             "Content-Type": "application/json"},
                )

            if r.status_code == 201:
                data = r.json()
                return PublishResult(
                    platform=self.platform_name, success=True,
                    url=data.get("url", "https://dev.to"),
                    post_id=str(data.get("id", "")),
                    image_path=image_url or "",
                )

            # Handle 422 "Title already used"
            if r.status_code == 422 and "already been used" in r.text.lower():
                ts = datetime.now().strftime("%b %d")
                payload["article"]["title"] = f"{title} ({ts})"
                async with httpx.AsyncClient(timeout=30) as client2:
                    r2 = await client2.post(
                        "https://dev.to/api/articles",
                        json=payload,
                        headers={"api-key": s.devto_api_key,
                                 "Content-Type": "application/json"},
                    )
                if r2.status_code == 201:
                    data = r2.json()
                    print(f"   ✅ Dev.to: published with updated title")
                    return PublishResult(
                        platform=self.platform_name, success=True,
                        url=data.get("url", "https://dev.to"),
                        post_id=str(data.get("id", "")),
                        image_path=image_url or "",
                    )
                return PublishResult(
                    platform=self.platform_name, success=False,
                    error="Title used recently. Auto-retry with date failed. Wait 5 minutes.",
                )

            return PublishResult(
                platform=self.platform_name, success=False,
                error=f"HTTP {r.status_code}: {r.text[:150]}",
            )
        except Exception as e:
            return PublishResult(platform=self.platform_name, success=False,
                                 error=str(e))