import asyncio
import time

import httpx

from src.config import settings
from src.redis_client import get_redis
from src.search.base import SearchBackend, RateLimitExceeded


async def _rate_limit_check(key: str, rpm: int) -> bool:
    """Sliding window rate limiter."""
    if rpm <= 0:
        return True
    r = await get_redis()
    now = time.time()
    pipe = r.pipeline()
    pipe.zremrangebyscore(f"rl:{key}", 0, now - 60)
    pipe.zadd(f"rl:{key}", {str(now): now})
    pipe.zcard(f"rl:{key}")
    pipe.expire(f"rl:{key}", 61)
    results = await pipe.execute()
    return results[2] <= rpm


class SearXNGBackend(SearchBackend):
    """SearXNG search backend (free, self-hosted via Tor)."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._client

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        if not await _rate_limit_check("searxng", settings.searxng_rate_limit):
            raise RateLimitExceeded("SearXNG rate limit exceeded")

        client = self._get_client()

        for attempt in range(3):
            try:
                resp = await client.get(
                    f"{settings.searxng_url}/search",
                    params={"q": query, "format": "json"},
                )
                resp.raise_for_status()
                data = resp.json()
                results = [
                    {
                        "url": r["url"],
                        "title": r.get("title", ""),
                        "snippet": r.get("content", ""),
                    }
                    for r in data.get("results", [])
                    if r.get("url")
                ]
                return results[:limit]
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500 and attempt < 2:
                    await asyncio.sleep(2**attempt)
                    continue
                return []
            except Exception:
                if attempt < 2:
                    await asyncio.sleep(2**attempt)
                    continue
                return []
        return []

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


# Global instance
_backend: SearXNGBackend | None = None


def get_search_backend() -> SearXNGBackend:
    global _backend
    if _backend is None:
        _backend = SearXNGBackend()
    return _backend


async def close_search_backend() -> None:
    global _backend
    if _backend:
        await _backend.close()
        _backend = None
