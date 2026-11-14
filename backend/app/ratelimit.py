import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class RateLimiter:
    """
    Sliding-window limit per client IP. In-process only: with several workers or servers, put the
    same limits on the reverse proxy (or move this to Redis).
    """

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def __call__(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                raise HTTPException(429, "Too many attempts. Please wait a minute and try again.")
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


check_mobile_limit = RateLimiter(20, 60)
register_limit = RateLimiter(5, 60)
otp_limit = RateLimiter(10, 60)
password_limit = RateLimiter(10, 60)
admin_login_limit = RateLimiter(10, 60)
ALL_LIMITERS = [check_mobile_limit, register_limit, otp_limit, password_limit, admin_login_limit]
