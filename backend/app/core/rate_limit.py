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
    # Once the key count crosses this, `check` sweeps out keys whose bucket is fully
    # expired. Keeps `_buckets` from growing forever as new users/orgs appear, without
    # doing a full scan on every call (only past the threshold).
    _EVICTION_KEY_THRESHOLD = 10_000

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
        if len(self._buckets) >= self._EVICTION_KEY_THRESHOLD:
            self._evict_stale_keys(cutoff)

    def _evict_stale_keys(self, cutoff: float) -> None:
        stale_keys = [k for k, bucket in self._buckets.items() if not bucket or bucket[-1] < cutoff]
        for stale_key in stale_keys:
            del self._buckets[stale_key]
