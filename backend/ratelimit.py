"""Small in-process rate limiter for auth and checkout endpoints.

Counts are kept per replica in memory, so with N replicas the effective limit is N times higher. That is still
enough to stop password guessing and reset-code brute force from a single client. Swap the store for Redis or a
MongoDB TTL collection if the app ever runs many replicas.
"""
import os
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import HTTPException, Request

_hits: Dict[str, Deque[float]] = defaultdict(deque)
_MAX_KEYS = 50_000


def client_ip(request: Request) -> str:
    # Behind the platform ingress the first X-Forwarded-For hop is the real client.
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def disabled() -> bool:
    """RATE_LIMITS=off turns limiting off, for automated test servers only."""
    return (os.environ.get("RATE_LIMITS") or "").strip().lower() in ("off", "0", "false", "disabled")


def check(key: str, limit: int, window_s: int) -> None:
    """Record one hit for `key`; raise 429 when more than `limit` hits fall inside `window_s` seconds."""
    if disabled():
        return
    now = time.monotonic()
    q = _hits[key]
    while q and q[0] <= now - window_s:
        q.popleft()
    if len(q) >= limit:
        retry = max(1, int(q[0] + window_s - now))
        raise HTTPException(status_code=429, detail=f"Too many attempts. Please try again in {retry} seconds.",
                            headers={"Retry-After": str(retry)})
    q.append(now)
    if len(_hits) > _MAX_KEYS:  # drop idle keys so memory stays bounded
        for k in [k for k, v in list(_hits.items()) if not v or v[-1] <= now - 3600]:
            _hits.pop(k, None)


def limit(name: str, per_ip: int, window_s: int):
    """FastAPI dependency: at most `per_ip` calls to this endpoint per client IP per window."""
    async def dep(request: Request):
        check(f"{name}:ip:{client_ip(request)}", per_ip, window_s)
    return dep


def reset() -> None:
    """Clear all counters (used by tests)."""
    _hits.clear()
