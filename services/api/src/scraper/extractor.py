import json
import logging
import random
import threading
import time
from urllib.parse import urlparse

import httpx
import trafilatura
from lxml import html as lxml_html

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
                    proxy=settings.proxy_url or None,
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


def fetch_and_extract(url: str, use_playwright: bool = False) -> dict:
    """Fetch URL and extract markdown content with metadata.

    Returns:
        Dict with markdown, title, author, date, description (or empty dict on failure)
    """
    if not use_playwright:
        try:
            _wait_for_domain(url)
            client = _get_client()
            resp = client.get(url, headers={"User-Agent": _get_random_ua()})
            resp.raise_for_status()
            content = extract_content(resp.text)
            if content.get("markdown"):
                logger.debug(f"Scraped {url}: {len(content['markdown'])} chars")
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

    return {}


def fetch_with_playwright(url: str, wait_after_load: int = 2000) -> dict:
    """Fetch URL using Playwright service for JS rendering.

    Returns:
        Dict with markdown and metadata (or empty dict on failure)
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
                return {}

            if status_code >= 400:
                logger.warning(f"Playwright HTTP {status_code} from {url}")
                return {}

            if content_html:
                content = extract_content(content_html)
                if content.get("markdown"):
                    logger.debug(f"Playwright scraped {url}: {len(content['markdown'])} chars")
                    return content

            logger.warning(f"Playwright empty content for {url}")
    except httpx.TimeoutException:
        logger.warning(f"Playwright timeout for {url}")
    except Exception as e:
        logger.error(f"Playwright error for {url}: {e}")
    return {}


MIN_CONTENT_LENGTH = 500


def extract_content(html: str) -> dict:
    """Extract markdown + metadata from HTML. Falls back to JSON-LD articleBody for short content."""
    doc = trafilatura.bare_extraction(html, include_tables=True, output_format="markdown")

    if doc:
        markdown = doc.text or ""
        meta = {
            "title": doc.title or None,
            "author": doc.author or None,
            "date": doc.date or None,
            "description": doc.description or None,
        }
    else:
        markdown = ""
        meta = {"title": None, "author": None, "date": None, "description": None}

    if len(markdown) < MIN_CONTENT_LENGTH:
        ld_content = _extract_jsonld_body(html)
        if ld_content and len(ld_content) > len(markdown):
            markdown = ld_content

    return {"markdown": markdown, **meta}


def _extract_jsonld_body(html: str) -> str:
    """Extract articleBody from Schema.org JSON-LD structured data."""
    try:
        tree = lxml_html.fromstring(html)
    except Exception:
        return ""

    for script in tree.xpath('//script[@type="application/ld+json"]'):
        try:
            data = json.loads(script.text_content())
            body = _find_article_body(data)
            if body and len(body) > MIN_CONTENT_LENGTH:
                return body
        except (json.JSONDecodeError, TypeError):
            continue
    return ""


def _find_article_body(data) -> str:
    if isinstance(data, dict):
        if "articleBody" in data:
            return data["articleBody"]
        for v in data.values():
            result = _find_article_body(v)
            if result:
                return result
    elif isinstance(data, list):
        for item in data:
            result = _find_article_body(item)
            if result:
                return result
    return ""


def close_client() -> None:
    """Close the HTTP client (call on shutdown)."""
    global _http_client
    if _http_client:
        _http_client.close()
        _http_client = None
