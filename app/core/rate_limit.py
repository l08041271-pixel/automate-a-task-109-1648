"""Tiny in-process fixed-window rate limiter.

No Redis, no extra infra — appropriate for a single small instance and for
keeping the free tier free. If you scale to multiple workers/instances,
replace the store with Redis or put the limit at the edge.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: int


class FixedWindowLimiter:
    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, *, cost: int = 1) -> RateLimitResult:
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) + cost > self.limit:
                retry_after = int(self.window - (now - bucket[0])) + 1 if bucket else self.window
                return RateLimitResult(False, 0, max(1, retry_after))
            for _ in range(cost):
                bucket.append(now)
            return RateLimitResult(True, max(0, self.limit - len(bucket)), 0)

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)
