"""
Distributed job queue for scraping.

Flow:
1. API creates job: SET job:{id}:total, LPUSH tasks to job:pending
2. Workers: BRPOP job:pending → scrape → HSET job:{id}:results
3. API polls: HLEN job:{id}:results until == total
"""
import asyncio
import hashlib
import json
import logging
import time
import uuid

from src.redis_client import get_redis, get_sync_redis
from src.config import settings

logger = logging.getLogger(__name__)


# --- Async API (for FastAPI) ---

async def create_job(urls: list[str], *, use_playwright: bool = False) -> str:
    """Create scrape job, returns job_id."""
    job_id = str(uuid.uuid4())[:8]
    r = await get_redis()

    # TTL = job_timeout + 60s buffer (for cleanup delay)
    ttl = settings.job_timeout + 60

    pipe = r.pipeline()
    pipe.set(f"job:{job_id}:total", len(urls))
    pipe.expire(f"job:{job_id}:total", ttl)
    pipe.expire(f"job:{job_id}:results", ttl)

    for url in urls:
        task = json.dumps({"job_id": job_id, "url": url, "use_playwright": use_playwright})
        pipe.lpush("job:pending", task)

    await pipe.execute()
    logger.info(f"Created job {job_id} with {len(urls)} URLs (TTL={ttl}s)")
    return job_id


async def get_results(job_id: str) -> list[tuple[str, str]]:
    """Wait for job completion, return [(url, content), ...].

    Returns partial results on timeout instead of raising exception.
    """
    r = await get_redis()
    deadline = time.time() + settings.job_timeout

    total = int(await r.get(f"job:{job_id}:total") or 0)
    if total == 0:
        return []

    done = 0
    while time.time() < deadline:
        done = await r.hlen(f"job:{job_id}:results")
        if done >= total:
            break
        await asyncio.sleep(settings.job_poll_interval)

    # Get whatever results we have (partial or complete)
    results_raw = await r.hgetall(f"job:{job_id}:results")
    await r.delete(f"job:{job_id}:total", f"job:{job_id}:results")

    if done < total:
        logger.warning(f"Job {job_id} timed out ({done}/{total} completed), returning partial results")
    else:
        logger.info(f"Job {job_id} completed: {len(results_raw)} results")

    return [(url, content) for url, content in results_raw.items()]


# --- Sync Worker (for worker process) ---

def pop_task(timeout: int = 5) -> dict | None:
    """Blocking pop from pending queue."""
    r = get_sync_redis()
    result = r.brpop("job:pending", timeout=timeout)
    if result:
        _, task_json = result
        try:
            return json.loads(task_json)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in queue: {task_json}")
            return None
    return None


def save_result(job_id: str, url: str, content: str) -> None:
    """Save scrape result."""
    r = get_sync_redis()
    r.hset(f"job:{job_id}:results", url, content)


# --- DLQ + Retry ---

MAX_RETRIES = 3


def add_to_dlq(job_id: str, url: str, error: str, attempt: int) -> None:
    """Add failed task to DLQ with exponential backoff."""
    r = get_sync_redis()
    if attempt < MAX_RETRIES:
        delay = 2 ** attempt
        retry_at = time.time() + delay
        task = json.dumps({
            "job_id": job_id,
            "url": url,
            "attempt": attempt + 1,
            "error": error,
        })
        r.zadd("job:dlq", {task: retry_at})
        logger.debug(f"DLQ: {url} retry {attempt + 1} in {delay}s")
    else:
        r.hset(f"job:{job_id}:failed", url, error)
        logger.warning(f"DLQ: {url} failed permanently: {error}")


def pop_dlq_ready() -> dict | None:
    """Atomically pop task ready for retry from DLQ."""
    r = get_sync_redis()
    now = time.time()

    # ZPOPMIN is atomic (no race condition)
    result = r.zpopmin("job:dlq", count=1)
    if not result:
        return None

    task_json, score = result[0]
    if score > now:
        # Not ready yet, put it back
        r.zadd("job:dlq", {task_json: score})
        return None

    try:
        return json.loads(task_json)
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in DLQ: {task_json}")
        return None


def get_dlq_stats() -> dict:
    """Get DLQ statistics."""
    r = get_sync_redis()
    return {
        "pending": r.zcard("job:dlq"),
        "ready": r.zcount("job:dlq", 0, time.time()),
    }


# --- Page Cache ---

def _cache_key(url: str) -> str:
    """Generate stable cache key from URL (no collisions)."""
    return f"page:{hashlib.md5(url.encode()).hexdigest()[:16]}"


def get_cached_page(url: str) -> str | None:
    """Get cached page content."""
    r = get_sync_redis()
    return r.get(_cache_key(url))


def set_cached_page(url: str, content: str) -> None:
    """Cache page content."""
    r = get_sync_redis()
    r.setex(_cache_key(url), settings.cache_ttl_page, content)
