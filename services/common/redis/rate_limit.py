import logging
from typing import Callable
from fastapi import HTTPException, Request, status

from .client import get_redis_client

log = logging.getLogger(__name__)


class RateLimitExceeded(HTTPException):
    def __init__(self, retry_after: int = 60):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Please try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )


async def check_rate_limit(
    key: str,
    limit: int,
    window_seconds: int = 60,
) -> None:
    redis_client = await get_redis_client()

    current = await redis_client.get(key)

    if current is None:
        await redis_client.setex(key, window_seconds, 1)
        log.debug(f"Rate limit initialized for {key}: 1/{limit}")
        return

    current_count = int(current)

    if current_count >= limit:
        ttl = await redis_client.ttl(key)
        log.warning(f"Rate limit exceeded for {key}: {current_count}/{limit}")
        raise RateLimitExceeded(retry_after=max(ttl, 1))

    new_count = await redis_client.incr(key)
    ttl = await redis_client.ttl(key)

    if ttl == -1:
        await redis_client.expire(key, window_seconds)
        log.warning(f"Rate limit key {key} had no TTL, set to {window_seconds}s")

    log.debug(f"Rate limit checked for {key}: {new_count}/{limit}")


def _client_ip(request: Request) -> str:
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        # Rightmost entry is the IP nginx actually saw
        return fwd.rsplit(",", 1)[-1].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(prefix: str, limit: int, window_seconds: int = 60) -> Callable:
    """FastAPI dependency factory — rate-limits per client IP.

    Was per-user keyed; switched to IP after the queue/status endpoints
    became anonymous. nginx in front of core sets X-Real-IP, see
    `_client_ip`.
    """

    async def dependency(request: Request) -> None:
        ip = _client_ip(request)
        await check_rate_limit(
            key=f"{prefix}:{ip}",
            limit=limit,
            window_seconds=window_seconds,
        )

    return dependency
