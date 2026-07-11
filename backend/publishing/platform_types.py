# backend/publishing/platform_types.py
# ─────────────────────────────────────────────────────────────────────────────
# PLATFORM TYPE SYSTEM
#
# Every platform belongs to a CONTENT TYPE. The content type determines:
# - Which format_agent function generates the content
# - Which state field stores the result
# - What formatting rules apply
#
# CONTENT TYPES:
# ┌──────────────────┬─────────────────────────────────────────────────────┐
# │ Type             │ Characteristics                                      │
# ├──────────────────┼─────────────────────────────────────────────────────┤
# │ BLOG             │ Long-form, Markdown, SEO, 1200-1800w, H1/H2/H3     │
# │ SOCIAL_LONG      │ 300-1900 chars, hook line, bullets, hashtags        │
# │ SOCIAL_SHORT     │ Very short, casual, question-driven, 1-2 hashtags   │
# │ THREAD           │ List of individual posts, each self-contained        │
# │ VIDEO_SCRIPT     │ (Future) spoken word format, scene descriptions      │
# └──────────────────┴─────────────────────────────────────────────────────┘
#
# PLATFORM → TYPE MAPPING:
# Dev.to      → BLOG          (blog_post field)
# Medium      → BLOG          (blog_post field)
# Substack    → BLOG          (blog_post field)
# LinkedIn    → SOCIAL_LONG   (linkedin_post field)
# Facebook    → SOCIAL_LONG   (linkedin_post field — reuses same content)
# Instagram   → SOCIAL_SHORT  (instagram_post field — future)
# Twitter/X   → THREAD        (twitter_thread field — list of tweets)
# Threads     → THREAD        (twitter_thread field — same format)
#
# HOW TO ADD A NEW PLATFORM:
# 1. Check if its content type already exists in CONTENT_TYPE_MAP
# 2. If YES: map it to an existing content field — no format_agent changes
# 3. If NO: add new type here + add new function in format_agent.py
# 4. Create platforms/yourplatform.py
# 5. Add to registry.py (one line)
# ─────────────────────────────────────────────────────────────────────────────

from enum import Enum


class ContentType(str, Enum):
    BLOG = "blog"             # Long-form articles
    SOCIAL_LONG = "social_long"   # LinkedIn-style posts
    SOCIAL_SHORT = "social_short" # Instagram-style captions (future)
    THREAD = "thread"         # Twitter/Threads-style


# Maps platform ID → ContentType
PLATFORM_TYPE_MAP: dict[str, ContentType] = {
    "blog":      ContentType.BLOG,
    "medium":    ContentType.BLOG,        # same as blog
    "substack":  ContentType.BLOG,        # same as blog
    "linkedin":  ContentType.SOCIAL_LONG,
    "facebook":  ContentType.SOCIAL_LONG, # reuses linkedin_post
    "instagram": ContentType.SOCIAL_SHORT,
    "twitter":   ContentType.THREAD,
    "threads":   ContentType.THREAD,      # Meta's Threads app
}

# Maps ContentType → which state field holds the content
CONTENT_TYPE_TO_FIELD: dict[ContentType, str] = {
    ContentType.BLOG:         "blog_post",
    ContentType.SOCIAL_LONG:  "linkedin_post",
    ContentType.SOCIAL_SHORT: "instagram_post",  # future field
    ContentType.THREAD:       "twitter_thread",
}

# Maps ContentType → human-readable label
CONTENT_TYPE_LABELS: dict[ContentType, str] = {
    ContentType.BLOG:         "Long-form blog article (Markdown, SEO-optimized, 1200-1800w)",
    ContentType.SOCIAL_LONG:  "Social post (hook + bullets + CTA, 1200-1600 chars)",
    ContentType.SOCIAL_SHORT: "Short caption (150-220 chars, emoji-friendly)",
    ContentType.THREAD:       "Thread (6-8 posts, each self-contained, <280 chars)",
}

# For each ContentType, what format_agent function generates it
CONTENT_TYPE_GENERATOR: dict[ContentType, str] = {
    ContentType.BLOG:         "_generate_blog_post",
    ContentType.SOCIAL_LONG:  "_generate_linkedin_post",
    ContentType.SOCIAL_SHORT: "_generate_instagram_caption",  # future
    ContentType.THREAD:       "_generate_twitter_thread",
}


def get_content_type(platform_id: str) -> ContentType:
    """Get the content type for a platform."""
    return PLATFORM_TYPE_MAP.get(platform_id, ContentType.BLOG)


def get_content_field(platform_id: str) -> str:
    """Get which state field stores content for this platform."""
    ctype = get_content_type(platform_id)
    return CONTENT_TYPE_TO_FIELD.get(ctype, "blog_post")


def get_unique_content_types(platforms: list[str]) -> list[ContentType]:
    """
    Given a list of platform IDs, return unique content types needed.

    Example:
        platforms = ["blog", "linkedin", "facebook", "twitter"]
        → [ContentType.BLOG, ContentType.SOCIAL_LONG, ContentType.THREAD]
        (facebook is deduplicated — same type as linkedin)

    This is what format_agent uses to avoid generating duplicate content.
    """
    seen = set()
    unique = []
    for platform in platforms:
        ctype = get_content_type(platform)
        if ctype not in seen:
            seen.add(ctype)
            unique.append(ctype)
    return unique


def explain_platform(platform_id: str) -> str:
    """Human-readable explanation of how content is generated for a platform."""
    ctype = get_content_type(platform_id)
    field = get_content_field(platform_id)
    label = CONTENT_TYPE_LABELS.get(ctype, "Unknown format")
    return f"{platform_id} → {ctype.value} type → stored in '{field}' → {label}"