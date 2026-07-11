# backend/publishing/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PublishResult:
    platform:   str
    success:    bool
    url:        str = ""
    post_id:    str = ""
    error:      str = ""
    image_path: str = ""
    metadata:   dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "platform":   self.platform,
            "success":    self.success,
            "url":        self.url,
            "post_id":    self.post_id,
            "error":      self.error,
            "image_used": bool(self.image_path),
        }


@dataclass
class PlatformContent:
    topic:          str
    tone:           str
    blog_post:      str = ""
    linkedin_post:  str = ""
    twitter_thread: list = field(default_factory=list)
    bluesky_post:   str = ""    # 220-295 chars, sharp
    telegram_post:  str = ""    # 800-1000 chars, HTML, image caption style
    image_path:     Optional[str] = None


class BasePlatformPublisher(ABC):
    platform_name:      str = ""
    platform_display:   str = ""
    platform_emoji:     str = ""
    content_field:      str = ""
    max_content_length: int = 0
    supports_images:    bool = True
    image_aspect_ratio: str = "1:1"

    @abstractmethod
    async def validate_credentials(self) -> tuple[bool, str]:
        pass

    @abstractmethod
    async def format_content(self, content: PlatformContent) -> PlatformContent:
        pass

    @abstractmethod
    async def publish(self, content: PlatformContent) -> PublishResult:
        pass

    async def run(self, content: PlatformContent) -> PublishResult:
        print(f"\n{self.platform_emoji} [{self.platform_display}] Starting...")
        valid, msg = await self.validate_credentials()
        if not valid:
            print(f"   ❌ Credentials invalid: {msg}")
            return PublishResult(platform=self.platform_name, success=False, error=msg)
        try:
            formatted = await self.format_content(content)
        except Exception as e:
            print(f"   ⚠️  Format error: {e}")
            formatted = content
        result = await self.publish(formatted)
        result.platform = self.platform_name
        print(f"   {'✅' if result.success else '❌'} {self.platform_display}: {result.url or result.error}")
        return result