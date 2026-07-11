# backend/security/rate_limiter.py

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from typing import Dict, Optional
from dataclasses import dataclass, field
from config import get_settings


@dataclass
class TokenBucket:
    """
    A single token bucket for one API key.

    INTERVIEW: "What is the token bucket algorithm?"
    ANSWER: "You have a bucket with capacity C. It starts full.
    Every request removes 1 token. Tokens are added back at rate R
    tokens per second (continuously, not in fixed windows). If the
    bucket is empty, the request is rejected. The math:
    available_tokens = min(capacity, tokens + (time_elapsed * rate))"
    """
    capacity: float          # Max tokens (burst limit)
    refill_rate: float       # Tokens per second
    tokens: float = 0.0      # Current tokens (starts full)
    last_refill: float = field(default_factory=time.time)

    def __post_init__(self):
        self.tokens = self.capacity  # Start with full bucket

    def consume(self, tokens: float = 1.0) -> bool:
        """
        Try to consume tokens. Returns True if allowed, False if rate limited.
        """
        now = time.time()

        # Refill: add tokens based on time elapsed
        elapsed = now - self.last_refill
        self.tokens = min(
            self.capacity,
            self.tokens + (elapsed * self.refill_rate)
        )
        self.last_refill = now

        # Check if enough tokens available
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    @property
    def available(self) -> float:
        """Current available tokens (after refill calculation)."""
        now = time.time()
        elapsed = now - self.last_refill
        return min(self.capacity, self.tokens + (elapsed * self.refill_rate))

    @property
    def retry_after(self) -> float:
        """Seconds until 1 token is available."""
        if self.available >= 1.0:
            return 0.0
        return (1.0 - self.available) / self.refill_rate


class RateLimiter:
    """
    Per-API-key token bucket rate limiter.

    Each unique API key gets its own independent bucket.
    New keys get a fresh full bucket on first request.

    INTERVIEW: "How does per-key rate limiting work?"
    ANSWER: "Each API key has its own independent token bucket stored
    in a dict keyed by the API key hash (not the raw key for security).
    This means a key that's being abused only affects itself — it doesn't
    impact other users. In a distributed system, you'd move the buckets
    to Redis so multiple server instances share the same state."
    """

    def __init__(self):
        self.settings = get_settings()
        self._buckets: Dict[str, TokenBucket] = {}

        # Rate: requests per window → tokens per second
        self.capacity = float(self.settings.rate_limit_requests)      # 60
        self.window = float(self.settings.rate_limit_window)          # 60 seconds
        self.refill_rate = self.capacity / self.window                 # 1.0/sec

    def _get_bucket(self, api_key: str) -> TokenBucket:
        """Get or create a bucket for this API key."""
        # Hash the key — don't store raw keys in memory
        import hashlib
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]

        if key_hash not in self._buckets:
            self._buckets[key_hash] = TokenBucket(
                capacity=self.capacity,
                refill_rate=self.refill_rate,
            )
        return self._buckets[key_hash]

    def check(self, api_key: str) -> dict:
        """
        Check if this API key is allowed to make a request.

        Returns:
            {
                "allowed": bool,
                "tokens_remaining": float,
                "retry_after": float (seconds, if not allowed)
            }
        """
        bucket = self._get_bucket(api_key)
        allowed = bucket.consume(1.0)

        return {
            "allowed": allowed,
            "tokens_remaining": round(bucket.available, 1),
            "retry_after": round(bucket.retry_after, 1) if not allowed else 0.0,
            "limit": int(self.capacity),
            "window": int(self.window),
        }

    def get_status(self, api_key: str) -> dict:
        """Get current rate limit status without consuming a token."""
        bucket = self._get_bucket(api_key)
        return {
            "tokens_remaining": round(bucket.available, 1),
            "capacity": int(self.capacity),
            "refill_rate": round(self.refill_rate, 2),
        }

    def reset(self, api_key: str) -> None:
        """Reset a specific key's bucket (admin use)."""
        import hashlib
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
        if key_hash in self._buckets:
            del self._buckets[key_hash]


# Singleton
_limiter_instance: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Returns the singleton rate limiter."""
    global _limiter_instance
    if _limiter_instance is None:
        _limiter_instance = RateLimiter()
    return _limiter_instance