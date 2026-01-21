import redis.asyncio as aioredis
import redis as sync_redis

from src.config import settings

_async_redis: aioredis.Redis | None = None
_sync_redis: sync_redis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Get async Redis client (for API)."""
    global _async_redis
    if _async_redis is None:
        _async_redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _async_redis


async def close_redis() -> None:
    global _async_redis
    if _async_redis:
        await _async_redis.close()
        _async_redis = None


def get_sync_redis() -> sync_redis.Redis:
    """Get sync Redis client (for workers)."""
    global _sync_redis
    if _sync_redis is None:
        _sync_redis = sync_redis.from_url(settings.redis_url, decode_responses=True)
    return _sync_redis
