# backend/publishing/platforms/twitter.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from publishing.base import BasePlatformPublisher, PlatformContent, PublishResult
from config import get_settings


class TwitterPublisher(BasePlatformPublisher):
    platform_name = "twitter"
    platform_display = "Twitter/X"
    platform_emoji = "🐦"
    content_field = "twitter_thread"
    max_content_length = 280
    supports_images = True
    image_aspect_ratio = "16:9"

    async def validate_credentials(self) -> tuple[bool, str]:
        s = get_settings()
        missing = [k for k, v in {
            "TWITTER_API_KEY": s.twitter_api_key,
            "TWITTER_API_SECRET": s.twitter_api_secret,
            "TWITTER_ACCESS_TOKEN": s.twitter_access_token,
            "TWITTER_ACCESS_SECRET": s.twitter_access_secret,
        }.items() if not v or v.startswith("your_")]
        if missing:
            return False, f"Missing: {', '.join(missing)}"
        return True, "Ready"

    async def format_content(self, content: PlatformContent) -> PlatformContent:
        """Ensure each tweet is under 280 characters."""
        formatted_tweets = []
        for tweet in content.twitter_thread:
            if len(tweet) > 279:
                tweet = tweet[:276] + "..."
            formatted_tweets.append(tweet)
        content.twitter_thread = formatted_tweets
        return content

    async def publish(self, content: PlatformContent) -> PublishResult:
        if not content.twitter_thread:
            return PublishResult(platform=self.platform_name, success=False,
                                 error="No tweets to post")
        try:
            import tweepy
            s = get_settings()
            client = tweepy.Client(
                consumer_key=s.twitter_api_key,
                consumer_secret=s.twitter_api_secret,
                access_token=s.twitter_access_token,
                access_token_secret=s.twitter_access_secret,
            )
            auth = tweepy.OAuth1UserHandler(
                s.twitter_api_key, s.twitter_api_secret,
                s.twitter_access_token, s.twitter_access_secret,
            )
            api_v1 = tweepy.API(auth)

            media_id = None
            if content.image_path and os.path.exists(content.image_path):
                try:
                    media = api_v1.media_upload(content.image_path)
                    media_id = media.media_id_string
                except Exception as e:
                    print(f"   ⚠️  Image upload failed: {e}")

            tweet_ids = []
            reply_to_id = None
            for i, tweet_text in enumerate(content.twitter_thread):
                kwargs = {"text": tweet_text}
                if reply_to_id:
                    kwargs["in_reply_to_tweet_id"] = reply_to_id
                if i == 0 and media_id:
                    kwargs["media_ids"] = [media_id]
                resp = client.create_tweet(**kwargs)
                tweet_ids.append(resp.data["id"])
                reply_to_id = resp.data["id"]

            me = client.get_me()
            username = me.data.username if me.data else "user"
            url = f"https://twitter.com/{username}/status/{tweet_ids[0]}"
            return PublishResult(platform=self.platform_name, success=True,
                                 url=url, post_id=tweet_ids[0],
                                 image_path=content.image_path or "")
        except ImportError:
            return PublishResult(platform=self.platform_name, success=False,
                                 error="Run: uv pip install tweepy")
        except Exception as e:
            return PublishResult(platform=self.platform_name, success=False,
                                 error=str(e))