# backend/publishing/platforms/telegram.py
# ─────────────────────────────────────────────────────────────────────────────
# Telegram Channel publishing via Bot API
#
# SETUP GUIDE (3 minutes):
#
# STEP 1 — Create a Bot:
#   1. Open Telegram → search for @BotFather → tap Start
#   2. Send: /newbot
#   3. Name: "AI Content Studio"
#   4. Username: "aicontentstudio_bot" (must end in _bot)
#   5. BotFather gives you a TOKEN like: 5123456:ABCdefGHIjklMNOpqrsTUVwxyz
#   → Save this as TELEGRAM_BOT_TOKEN
#
# STEP 2 — Create or use a Channel:
#   1. In Telegram → New Channel → give it a name and username
#      e.g. @aicontentstudio_channel
#   2. Make it Public so posts are visible
#   3. Go to Channel Info → Add Admins → search your bot → add it
#      Give it "Post Messages" permission
#   → Your channel username is TELEGRAM_CHAT_ID (e.g. @aicontentstudio_channel)
#
# STEP 3 — Add to .env:
#   TELEGRAM_BOT_TOKEN=5123456:ABCdefGHIjklMNOpqrsTUVwxyz
#   TELEGRAM_CHAT_ID=@aicontentstudio_channel
#
# WHY TELEGRAM:
# - Free API, no approval needed
# - Channels can have unlimited subscribers
# - Supports images + HTML captions
# - Developer/tech communities very active on Telegram
# - Perfect for newsletter-style content with images
# ─────────────────────────────────────────────────────────────────────────────

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import httpx
from publishing.base import BasePlatformPublisher, PlatformContent, PublishResult
from config import get_settings


class TelegramPublisher(BasePlatformPublisher):
    platform_name    = "telegram"
    platform_display = "Telegram Channel"
    platform_emoji   = "✈️"
    content_field    = "telegram_post"
    max_content_length = 1024   # Caption limit when sending with image
    supports_images  = True
    image_aspect_ratio = "16:9"

    BASE = "https://api.telegram.org"

    async def validate_credentials(self) -> tuple[bool, str]:
        s = get_settings()
        if not s.telegram_bot_token:
            return False, "Missing TELEGRAM_BOT_TOKEN — create via @BotFather"
        # Support both TELEGRAM_CHANNEL_ID and TELEGRAM_CHAT_ID
        chat_id = s.telegram_channel_id or s.telegram_chat_id
        if not chat_id:
            return False, "Missing TELEGRAM_CHANNEL_ID in .env — use @your_channel_name"
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(f"{self.BASE}/bot{s.telegram_bot_token}/getMe")
                if r.status_code == 200:
                    bot_name = r.json().get("result", {}).get("username", "?")
                    return True, f"Ready — @{bot_name}"
                return False, f"Invalid token: HTTP {r.status_code}"
        except Exception as e:
            return False, f"Connection error: {e}"

    async def format_content(self, content: PlatformContent) -> PlatformContent:
        """
        Telegram posts use HTML formatting.
        Convert any leftover markdown to HTML.
        """
        import re
        text = content.telegram_post or content.bluesky_post or ""

        # Convert markdown to Telegram HTML
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)  # **bold** → <b>bold</b>
        text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)       # *italic* → <i>italic</i>
        text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
        text = re.sub(r'_(.+?)_', r'<i>\1</i>', text)

        if len(text) > 1020:
            text = text[:1017] + "…"

        content.telegram_post = text
        return content

    async def publish(self, content: PlatformContent) -> PublishResult:
        post_text = content.telegram_post
        if not post_text:
            return PublishResult(platform=self.platform_name, success=False,
                                 error="No post content")

        s = get_settings()
        token   = s.telegram_bot_token
        # Support TELEGRAM_CHANNEL_ID (primary) and TELEGRAM_CHAT_ID (legacy)
        chat_id = s.telegram_channel_id or s.telegram_chat_id

        # Ensure chat_id starts with @ for public channels
        if chat_id and not chat_id.startswith("@") and not chat_id.lstrip("-").isdigit():
            chat_id = f"@{chat_id}"

        try:
            image_url = content.image_path

            if image_url and isinstance(image_url, str) and image_url.startswith("http"):
                # Send image with caption — most impactful format
                payload = {
                    "chat_id":    chat_id,
                    "photo":      image_url,
                    "caption":    post_text[:1024],
                    "parse_mode": "HTML",
                }
                endpoint = f"{self.BASE}/bot{token}/sendPhoto"
                print(f"   📸 Sending Telegram photo with caption ({len(post_text)} chars)…")
            else:
                # Text-only message (up to 4096 chars)
                payload = {
                    "chat_id":    chat_id,
                    "text":       post_text[:4096],
                    "parse_mode": "HTML",
                }
                endpoint = f"{self.BASE}/bot{token}/sendMessage"
                print(f"   📝 Sending Telegram text message ({len(post_text)} chars)…")

            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post(endpoint, json=payload)

            if r.status_code == 200:
                data   = r.json().get("result", {})
                msg_id = data.get("message_id", "")
                # Build URL if channel username is available
                channel = chat_id.lstrip("@")
                url = f"https://t.me/{channel}/{msg_id}" if channel and msg_id else "https://t.me"
                print(f"   ✅ Telegram published: {url}")
                return PublishResult(
                    platform=self.platform_name, success=True,
                    url=url, post_id=str(msg_id),
                    image_path=image_url or "",
                )

            err = r.json().get("description", r.text[:150])
            print(f"   ❌ Telegram: {r.status_code} — {err}")

            # Handle common errors with helpful messages
            if "chat not found" in err.lower():
                err = (
                    f"Channel '{chat_id}' not found. "
                    "Check TELEGRAM_CHAT_ID and ensure bot is an admin in the channel."
                )
            elif "bot is not a member" in err.lower():
                err = (
                    "Bot is not a member of the channel. "
                    "Add bot as admin: Channel → Edit → Administrators → add your bot."
                )

            return PublishResult(platform=self.platform_name, success=False, error=err)

        except Exception as e:
            print(f"   ❌ Telegram error: {e}")
            return PublishResult(platform=self.platform_name, success=False, error=str(e))