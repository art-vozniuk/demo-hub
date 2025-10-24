import logging
from typing import Callable, Any
from fastapi import HTTPException, status, Depends

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


def rate_limit(
    prefix: str,
    limit: int,
    window_seconds: int = 60,
    get_current_user: Callable | None = None,
) -> Callable:
    async def dependency(current_user: Any = Depends(get_current_user)) -> None:
        user_id = getattr(current_user, "id", "anonymous")
        await check_rate_limit(
            key=f"{prefix}:{user_id}",
            limit=limit,
            window_seconds=window_seconds,
        )

    return dependency
