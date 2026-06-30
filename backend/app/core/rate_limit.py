"""Lightweight in-process rate limiting.

Sliding-window counter keyed by an arbitrary string (e.g. "user:<id>" or "org:<id>").
This is in-process only — accurate for a single backend instance. If the app is ever
scaled to multiple instances, back this with a shared store (e.g. Redis INCR + TTL)
instead of the in-memory dict; the call sites below would not need to change.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from app.core.exceptions import ApiError


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, *, limit: int, window_seconds: float = 60.0) -> None:
        """Raise ApiError(429) if `key` has exceeded `limit` events in `window_seconds`."""
        now = time.monotonic()
        bucket = self._buckets[key]
        cutoff = now - window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(1, int(window_seconds - (now - bucket[0])))
            raise ApiError(
                429,
                "RATE_LIMITED",
                "Too many requests. Please slow down and try again shortly.",
                details={"retry_after_seconds": retry_after},
            )
        bucket.append(now)
