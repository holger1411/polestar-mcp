"""
Simple TTL cache for Polestar API responses.

Different data types have different TTLs:
- Battery/status: 3 minutes (changes frequently while charging)
- Vehicle info: 24 hours (rarely changes)
- Health: 30 minutes (changes infrequently)
"""

import hashlib
import json
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Default TTLs per data type (seconds)
DEFAULT_TTLS = {
    "status": 180,        # 3 minutes — battery/charging changes often
    "vehicle_info": 86400,  # 24 hours — VIN/model/specs are static
    "health": 1800,       # 30 minutes
    "default": 300,       # 5 minutes fallback
}


class CacheEntry:
    """A single cached value with expiration."""

    __slots__ = ("data", "expires_at")

    def __init__(self, data: Any, ttl: int):
        self.data = data
        self.expires_at = time.time() + ttl

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at


class CacheManager:
    """
    In-memory TTL cache for API responses.

    Keeps things simple — no disk persistence needed for a local MCP server.
    """

    def __init__(self, max_size: int = 500):
        self._store: dict[str, CacheEntry] = {}
        self._max_size = max_size

    def get(self, key: str) -> Optional[Any]:
        """Return cached data or None if missing/expired."""
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.is_expired:
            del self._store[key]
            logger.debug("Cache EXPIRED: %s", key)
            return None
        logger.debug("Cache HIT: %s", key)
        return entry.data

    def set(self, key: str, data: Any, data_type: str = "default") -> None:
        """Store data with TTL based on data_type."""
        # Evict oldest entries if at capacity
        if len(self._store) >= self._max_size:
            self._evict_expired()

        ttl = DEFAULT_TTLS.get(data_type, DEFAULT_TTLS["default"])
        self._store[key] = CacheEntry(data, ttl)
        logger.debug("Cache SET: %s (ttl=%ds, type=%s)", key, ttl, data_type)

    def invalidate(self, key: str) -> None:
        """Remove a specific cache entry."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Remove all cached entries."""
        self._store.clear()
        logger.debug("Cache cleared")

    def _evict_expired(self) -> None:
        """Remove all expired entries."""
        expired_keys = [k for k, v in self._store.items() if v.is_expired]
        for k in expired_keys:
            del self._store[k]
        logger.debug("Evicted %d expired entries", len(expired_keys))

    @staticmethod
    def make_key(operation: str, **kwargs) -> str:
        """Generate a deterministic cache key."""
        parts = json.dumps(kwargs, sort_keys=True, default=str)
        digest = hashlib.md5(parts.encode()).hexdigest()[:12]
        return f"polestar:{operation}:{digest}"
