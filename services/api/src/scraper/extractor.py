import logging
import random
import threading
import time
from urllib.parse import urlparse

import httpx
import trafilatura

from src.config import settings

logger = logging.getLogger(__name__)

# Realistic User-Agent rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# Connection pool (thread-safe singleton)
_http_client: httpx.Client | None = None
_client_lock = threading.Lock()

# Per-domain rate limiting
_domain_last_request: dict[str, float] = {}
_domain_lock = threading.Lock()
DOMAIN_DELAY = 1.0  # seconds between requests to same domain


def _get_client() -> httpx.Client:
    """Get or create shared HTTP client with connection pooling."""
    global _http_client
    if _http_client is None:
        with _client_lock:
            if _http_client is None:
                _http_client = httpx.Client(
                    timeout=settings.scrape_timeout,
                    follow_redirects=True,
                    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                )
    return _http_client


def _wait_for_domain(url: str) -> None:
    """Rate limit requests per domain."""
    domain = urlparse(url).netloc
    with _domain_lock:
        last = _domain_last_request.get(domain, 0)
        elapsed = time.time() - last
        if elapsed < DOMAIN_DELAY:
            time.sleep(DOMAIN_DELAY - elapsed)
        _domain_last_request[domain] = time.time()


def _get_random_ua() -> str:
    """Get random User-Agent."""
    return random.choice(USER_AGENTS)


def fetch_and_extract(url: str, use_playwright: bool = False) -> str:
    """Fetch URL and extract markdown content.

    Args:
        url: URL to fetch
        use_playwright: Force Playwright (for SPA sites)

    Returns:
        Extracted markdown or empty string on failure
    """
    if not use_playwright:
        try:
            _wait_for_domain(url)
            client = _get_client()
            resp = client.get(url, headers={"User-Agent": _get_random_ua()})
            resp.raise_for_status()
            content = extract_content(resp.text)
            if content:
                logger.debug(f"Scraped {url}: {len(content)} chars")
                return content
            logger.warning(f"Empty content from {url}")
        except httpx.TimeoutException:
            logger.warning(f"Timeout scraping {url}")
        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP {e.response.status_code} from {url}")
        except Exception as e:
            logger.error(f"Failed to scrape {url}: {e}")

    # Fallback to Playwright if configured
    if settings.playwright_url:
        return fetch_with_playwright(url)

    return ""


def fetch_with_playwright(url: str, wait_after_load: int = 2000) -> str:
    """Fetch URL using Playwright service for JS rendering.

    Args:
        url: URL to fetch
        wait_after_load: Additional wait time after page load (ms)

    Returns:
        Extracted markdown or empty string on failure
    """
    try:
        _wait_for_domain(url)
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                f"{settings.playwright_url}/scrape",
                json={
                    "url": url,
                    "wait_after_load": wait_after_load,
                    "timeout": 30000,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            status_code = data.get("pageStatusCode", 0)
            page_error = data.get("pageError")
            content_html = data.get("content", "")

            if page_error:
                logger.warning(f"Playwright error for {url}: {page_error} (HTTP {status_code})")
                return ""

            if status_code >= 400:
                logger.warning(f"Playwright HTTP {status_code} from {url}")
                return ""

            if content_html:
                content = extract_content(content_html)
                if content:
                    logger.debug(f"Playwright scraped {url}: {len(content)} chars")
                    return content

            logger.warning(f"Playwright empty content for {url}")
    except httpx.TimeoutException:
        logger.warning(f"Playwright timeout for {url}")
    except Exception as e:
        logger.error(f"Playwright error for {url}: {e}")
    return ""


def extract_content(html: str) -> str:
    """Extract markdown from HTML."""
    return trafilatura.extract(html, include_tables=True, output_format="markdown") or ""


def close_client() -> None:
    """Close the HTTP client (call on shutdown)."""
    global _http_client
    if _http_client:
        _http_client.close()
        _http_client = None
