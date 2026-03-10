import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException

from src.api.auth import verify_api_key
from src.api.schemas import SearchRequest, SearchResponse, SearchResultItem, ScrapeRequest
from src.search import RateLimitExceeded
from src.search.searxng import get_search_backend
from src.scraper.queue import create_job, get_results
from src.redis_client import get_redis
from src.config import settings

router = APIRouter(prefix="/v1", dependencies=[Depends(verify_api_key)])


def _cache_key(query: str, limit: int) -> str:
    return hashlib.md5(f"{query}:{limit}".encode()).hexdigest()[:16]


@router.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest) -> SearchResponse:
    r = await get_redis()
    cache_key = f"search:{_cache_key(req.query, req.limit)}"

    # Check cache
    cached = await r.get(cache_key)
    if cached:
        return SearchResponse(success=True, data=json.loads(cached))

    # Search for URLs
    try:
        backend = get_search_backend()
        urls = await backend.search(req.query, req.limit)
    except RateLimitExceeded:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    if not urls:
        return SearchResponse(success=True, data=[])

    # Create scrape job and wait for results (returns partial on timeout)
    job_id = await create_job(urls)
    results = await get_results(job_id)

    # Build response
    data = [SearchResultItem(url=url, markdown=md) for url, md in results if md]

    # Cache results
    await r.setex(
        cache_key,
        settings.cache_ttl_search,
        json.dumps([{"url": d.url, "markdown": d.markdown} for d in data]),
    )

    return SearchResponse(success=True, data=data)


@router.post("/scrape", response_model=SearchResponse)
async def scrape(req: ScrapeRequest) -> SearchResponse:
    job_id = await create_job(req.urls, use_playwright=req.use_playwright)
    results = await get_results(job_id)

    data = [SearchResultItem(url=url, markdown=md) for url, md in results if md]
    return SearchResponse(success=True, data=data)
