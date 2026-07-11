# backend/publishing/registry.py
from publishing.platforms.twitter  import TwitterPublisher
from publishing.platforms.linkedin import LinkedInPublisher
from publishing.platforms.devto    import DevToPublisher
from publishing.platforms.bluesky  import BlueskyPublisher
from publishing.platforms.telegram import TelegramPublisher

PLATFORM_REGISTRY: dict = {
    "twitter":  TwitterPublisher,
    "linkedin": LinkedInPublisher,
    "blog":     DevToPublisher,
    "bluesky":  BlueskyPublisher,
    "telegram": TelegramPublisher,
}

AUTO_POST_RESTRICTED = {
    "linkedin": "LinkedIn restricts personal profile API posting.",
    "twitter":  "Twitter free tier is read-only. Posting requires Basic plan ($100/mo).",
}

COPY_INSTRUCTIONS = {
    "twitter":  ("🐦", "Twitter/X",        "https://twitter.com/compose/tweet"),
    "linkedin": ("💼", "LinkedIn",          "https://linkedin.com/feed"),
    "blog":     ("📝", "Dev.to",            "https://dev.to/new"),
    "bluesky":  ("☁️", "Bluesky",           "https://bsky.app"),
    "telegram": ("✈️", "Telegram Channel",  "https://t.me"),
}


def get_publisher(platform: str):
    cls = PLATFORM_REGISTRY.get(platform)
    if not cls:
        raise ValueError(f"Unknown platform: '{platform}'")
    return cls()


async def get_platform_status() -> list[dict]:
    statuses = []
    for name, cls in PLATFORM_REGISTRY.items():
        instance = cls()
        valid, message = await instance.validate_credentials()
        emoji, display, copy_url = COPY_INSTRUCTIONS.get(name, ("📌", name, ""))
        statuses.append({
            "id":          name,
            "display":     instance.platform_display,
            "emoji":       instance.platform_emoji,
            "configured":  valid,
            "message":     message,
            "copy_url":    copy_url,
            "auto_post_restricted": name in AUTO_POST_RESTRICTED,
            "restriction_reason":   AUTO_POST_RESTRICTED.get(name, ""),
        })
    return statuses