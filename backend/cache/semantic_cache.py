# backend/cache/semantic_cache.py

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import hashlib
from typing import Optional, Any
from dataclasses import dataclass, field
import numpy as np

from rag.embeddings import embed_single, compute_similarity
from config import get_settings


@dataclass
class CacheEntry:
    """
    One cached result with metadata.
    """
    query: str              # Original query string
    query_embedding: np.ndarray   # Embedded query vector
    result: Any             # The full pipeline result (ContentState)
    topic: str              # Topic for display
    tone: str               # Tone used
    created_at: float = field(default_factory=time.time)
    hit_count: int = 0      # How many times this entry was served
    last_hit: float = field(default_factory=time.time)


class SemanticCache:
    """
    In-memory semantic cache for pipeline results.

    Uses cosine similarity between query embeddings to find
    near-duplicate requests and serve cached results.

    INTERVIEW: "How is semantic cache different from a regular dict cache?"
    ANSWER: "A dict cache does exact string matching — the key must match
    character-for-character. Semantic cache embeds both the stored query
    and the new query into vector space, then computes cosine similarity.
    If similarity exceeds the threshold, it's a cache hit regardless of
    exact wording. This is the difference between a lookup table and
    approximate nearest-neighbor search."
    """

    def __init__(self):
        self.settings = get_settings()
        self.entries: list[CacheEntry] = []
        self.threshold = self.settings.cache_similarity_threshold  # 0.92
        self.max_size = self.settings.cache_max_size  # 100
        self.stats = {"hits": 0, "misses": 0, "evictions": 0}

    def get(self, query: str, tone: str = "") -> Optional[Any]:
        """
        Look up a query in the cache.

        Args:
            query: The search query / topic
            tone: Tone parameter (cache is tone-specific)

        Returns:
            Cached result if found, None otherwise

        Time complexity: O(n) where n = cache size.
        For n=100 this is ~5ms — negligible vs 60s pipeline.
        At n=10,000 you'd switch to FAISS for cache lookup too.
        """
        if not self.entries:
            self.stats["misses"] += 1
            return None

        try:
            query_vec = embed_single(query)
        except Exception:
            self.stats["misses"] += 1
            return None

        best_score = -1.0
        best_entry = None

        for entry in self.entries:
            # Only match same tone
            if entry.tone != tone:
                continue

            score = compute_similarity(query_vec, entry.query_embedding)
            if score > best_score:
                best_score = score
                best_entry = entry

        if best_entry and best_score >= self.threshold:
            # Cache hit
            best_entry.hit_count += 1
            best_entry.last_hit = time.time()
            self.stats["hits"] += 1

            print(f"🎯 Cache HIT (similarity: {best_score:.3f})")
            print(f"   Query: '{query[:50]}'")
            print(f"   Matched: '{best_entry.query[:50]}'")
            print(f"   Serving cached result (saved ~60s)")

            return best_entry.result

        self.stats["misses"] += 1
        return None

    def set(self, query: str, tone: str, result: Any, topic: str = "") -> None:
        """
        Store a result in the cache.

        Uses LRU (Least Recently Used) eviction when full.

        INTERVIEW: "What eviction policy did you use?"
        ANSWER: "LRU — Least Recently Used. When the cache is full,
        we evict the entry that was accessed least recently. LRU works
        well for content caches because popular topics get queried again,
        while obscure one-time queries naturally age out."
        """
        try:
            query_vec = embed_single(query)
        except Exception:
            return  # Don't crash if embedding fails

        # Evict if at capacity (LRU)
        if len(self.entries) >= self.max_size:
            # Sort by last_hit, remove oldest
            self.entries.sort(key=lambda e: e.last_hit)
            evicted = self.entries.pop(0)
            self.stats["evictions"] += 1
            print(f"🗑️  Cache evicted: '{evicted.query[:40]}' "
                  f"(hit {evicted.hit_count}x)")

        entry = CacheEntry(
            query=query,
            query_embedding=query_vec,
            result=result,
            topic=topic,
            tone=tone,
        )
        self.entries.append(entry)
        print(f"💾 Cached result for: '{query[:50]}' "
              f"[{len(self.entries)}/{self.max_size}]")

    def invalidate_by_session(self, session_id: str) -> bool:
        """
        Remove the cache entry whose stored result has this session_id.
        Called when content is REJECTED so the next generation of the same
        topic produces fresh content instead of re-serving the rejected one.

        Returns True if an entry was removed.
        """
        for i, entry in enumerate(self.entries):
            res = entry.result
            # result is a dict (ContentState) carrying session_id
            if isinstance(res, dict) and res.get("session_id") == session_id:
                self.entries.pop(i)
                print(f"🗑️  Cache invalidated (rejected): '{entry.query[:40]}'")
                return True
        return False

    def invalidate_by_topic(self, topic: str, tone: str = "") -> int:
        """
        Remove cache entries matching a topic (and optionally tone). Fallback
        used when we don't have a session_id. Matches on the stored topic
        string case-insensitively. Returns count removed.
        """
        topic_l = topic.strip().lower()
        before = len(self.entries)
        self.entries = [
            e for e in self.entries
            if not (e.topic.strip().lower() == topic_l and (not tone or e.tone == tone))
        ]
        removed = before - len(self.entries)
        if removed:
            print(f"🗑️  Cache invalidated {removed} entr(ies) for topic: '{topic[:40]}'")
        return removed

    def get_stats(self) -> dict:
        """Return cache performance statistics."""
        total = self.stats["hits"] + self.stats["misses"]
        hit_rate = (self.stats["hits"] / total * 100) if total > 0 else 0
        return {
            "hits": self.stats["hits"],
            "misses": self.stats["misses"],
            "evictions": self.stats["evictions"],
            "hit_rate_pct": round(hit_rate, 1),
            "cache_size": len(self.entries),
            "max_size": self.max_size,
            "threshold": self.threshold,
        }

    def clear(self) -> None:
        """Clear all cache entries."""
        self.entries.clear()
        self.stats = {"hits": 0, "misses": 0, "evictions": 0}


# Singleton
_cache_instance: Optional[SemanticCache] = None


def get_cache() -> SemanticCache:
    """Returns the singleton semantic cache."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = SemanticCache()
    return _cache_instance