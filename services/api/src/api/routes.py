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


def _cache_key(query: str, limit: int, scrape: bool) -> str:
    return hashlib.md5(f"{query}:{limit}:{scrape}".encode()).hexdigest()[:16]


def _result_item(url: str, content: dict) -> SearchResultItem:
    return SearchResultItem(
        url=url,
        markdown=content.get("markdown", ""),
        title=content.get("title"),
        author=content.get("author"),
        date=content.get("date"),
        description=content.get("description"),
    )


@router.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest) -> SearchResponse:
    r = await get_redis()
    cache_key = f"search:{_cache_key(req.query, req.limit, req.scrape)}"

    # Check cache
    cached = await r.get(cache_key)
    if cached:
        return SearchResponse(success=True, data=json.loads(cached))

    # Search for URLs
    try:
        backend = get_search_backend()
        search_results = await backend.search(req.query, req.limit)
    except RateLimitExceeded:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    if not search_results:
        return SearchResponse(success=True, data=[])

    # Search-only mode: return snippets without scraping
    if not req.scrape:
        data = [
            SearchResultItem(
                url=sr["url"],
                markdown=sr.get("snippet", ""),
                title=sr.get("title") or None,
            )
            for sr in search_results
        ]
    else:
        # Create scrape job and wait for results
        urls = [sr["url"] for sr in search_results]
        job_id = await create_job(urls)
        results = await get_results(job_id)
        data = [_result_item(url, content) for url, content in results if content.get("markdown")]

    # Cache results
    await r.setex(
        cache_key,
        settings.cache_ttl_search,
        json.dumps([d.model_dump() for d in data]),
    )

    return SearchResponse(success=True, data=data)


@router.post("/scrape", response_model=SearchResponse)
async def scrape(req: ScrapeRequest) -> SearchResponse:
    job_id = await create_job(req.urls, use_playwright=req.use_playwright)
    results = await get_results(job_id)

    data = [_result_item(url, content) for url, content in results if content.get("markdown")]
    return SearchResponse(success=True, data=data)
