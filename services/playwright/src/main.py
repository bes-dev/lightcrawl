"""
Playwright Service for LightCrawl.

Microservice for JavaScript rendering with anti-bot measures.
Based on Firecrawl's playwright-service architecture.
"""
import asyncio
import logging
import os
import random
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from playwright.async_api import async_playwright, Browser, Page
from pydantic import BaseModel

# Configuration
MAX_CONCURRENT_PAGES = int(os.getenv("MAX_CONCURRENT_PAGES", "10"))
DEFAULT_TIMEOUT = int(os.getenv("TIMEOUT", "30000"))
BLOCK_MEDIA = os.getenv("BLOCK_MEDIA", "true").lower() == "true"
PROXY_URL = os.getenv("PROXY_URL")  # http://user:pass@host:port

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("playwright-service")

# Realistic User Agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# Ad-serving domains to block
AD_DOMAINS = [
    "doubleclick.net",
    "adservice.google.com",
    "googlesyndication.com",
    "googletagservices.com",
    "googletagmanager.com",
    "google-analytics.com",
    "adnxs.com",
    "ads-twitter.com",
    "facebook.net",
    "fbcdn.net",
    "amazon-adsystem.com",
    "criteo.com",
    "outbrain.com",
    "taboola.com",
]

# Media extensions to block
MEDIA_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
    ".mp3", ".mp4", ".avi", ".webm", ".ogg", ".wav", ".flac",
    ".woff", ".woff2", ".ttf", ".eot",
)


class Semaphore:
    """Async semaphore for concurrency control."""

    def __init__(self, max_permits: int):
        self._semaphore = asyncio.Semaphore(max_permits)
        self._max = max_permits
        self._active = 0

    async def acquire(self):
        await self._semaphore.acquire()
        self._active += 1

    def release(self):
        self._active -= 1
        self._semaphore.release()

    @property
    def active(self) -> int:
        return self._active

    @property
    def available(self) -> int:
        return self._max - self._active


# Global state
browser: Optional[Browser] = None
page_semaphore = Semaphore(MAX_CONCURRENT_PAGES)


class ScrapeRequest(BaseModel):
    url: str
    wait_after_load: int = 0  # Additional wait after page load (ms)
    timeout: int = DEFAULT_TIMEOUT  # Page load timeout (ms)
    headers: Optional[dict[str, str]] = None
    check_selector: Optional[str] = None  # Wait for specific selector
    skip_tls_verification: bool = False


class ScrapeResponse(BaseModel):
    content: str
    pageStatusCode: int
    pageError: Optional[str] = None
    contentType: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    maxConcurrentPages: int
    activePages: int
    availablePages: int


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage browser lifecycle."""
    global browser

    logger.info("Starting Playwright browser...")
    playwright = await async_playwright().start()

    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-accelerated-2d-canvas",
            "--no-first-run",
            "--no-zygote",
            "--disable-gpu",
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-sync",
            "--disable-translate",
            "--metrics-recording-only",
            "--mute-audio",
            "--no-first-run",
            "--safebrowsing-disable-auto-update",
        ],
    )
    logger.info(f"Browser started. Max concurrent pages: {MAX_CONCURRENT_PAGES}")

    yield

    logger.info("Closing browser...")
    await browser.close()
    await playwright.stop()


app = FastAPI(title="Playwright Service", lifespan=lifespan)


async def block_resources(route, request):
    """Block ads and optionally media."""
    url = request.url.lower()

    # Block ad domains
    for domain in AD_DOMAINS:
        if domain in url:
            await route.abort()
            return

    # Block media if enabled
    if BLOCK_MEDIA and url.endswith(MEDIA_EXTENSIONS):
        await route.abort()
        return

    await route.continue_()


async def scrape_page(
    page: Page,
    url: str,
    wait_after_load: int,
    timeout: int,
    check_selector: Optional[str],
) -> ScrapeResponse:
    """Scrape a single page with proper waiting."""
    try:
        # Navigate to URL
        response = await page.goto(url, wait_until="load", timeout=timeout)

        if response is None:
            return ScrapeResponse(
                content="",
                pageStatusCode=0,
                pageError="Navigation failed - no response",
            )

        status_code = response.status
        content_type = response.headers.get("content-type", "")

        # Additional wait for dynamic content
        if wait_after_load > 0:
            await page.wait_for_timeout(wait_after_load)

        # Wait for specific selector if provided
        if check_selector:
            try:
                await page.wait_for_selector(check_selector, timeout=timeout)
            except Exception:
                return ScrapeResponse(
                    content="",
                    pageStatusCode=status_code,
                    pageError=f"Selector '{check_selector}' not found",
                    contentType=content_type,
                )

        # Get content
        if "application/json" in content_type or "text/plain" in content_type:
            # Return raw body for JSON/plain text
            body = await response.body()
            content = body.decode("utf-8", errors="replace")
        else:
            # Return full HTML for web pages
            content = await page.content()

        # Determine error message for non-2xx
        page_error = None
        if status_code >= 300:
            page_error = get_status_error(status_code)

        return ScrapeResponse(
            content=content,
            pageStatusCode=status_code,
            pageError=page_error,
            contentType=content_type,
        )

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Scrape error for {url}: {error_msg}")

        # Determine status code from error
        if "timeout" in error_msg.lower():
            return ScrapeResponse(content="", pageStatusCode=408, pageError="Timeout")
        elif "net::ERR_" in error_msg:
            return ScrapeResponse(
                content="", pageStatusCode=0, pageError=f"Network error: {error_msg}"
            )
        else:
            return ScrapeResponse(
                content="", pageStatusCode=500, pageError=error_msg
            )


def get_status_error(status_code: int) -> str:
    """Get error message for HTTP status code."""
    errors = {
        301: "Moved Permanently",
        302: "Found (Redirect)",
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        429: "Too Many Requests",
        500: "Internal Server Error",
        502: "Bad Gateway",
        503: "Service Unavailable",
        504: "Gateway Timeout",
    }
    return errors.get(status_code, f"HTTP Error {status_code}")


@app.post("/scrape", response_model=ScrapeResponse)
async def scrape(req: ScrapeRequest) -> ScrapeResponse:
    """Scrape a URL with JavaScript rendering."""
    if browser is None:
        raise HTTPException(status_code=503, detail="Browser not initialized")

    # Acquire semaphore (wait if at max concurrency)
    await page_semaphore.acquire()

    try:
        # Random User-Agent
        user_agent = random.choice(USER_AGENTS)

        # Context options
        context_options = {
            "user_agent": user_agent,
            "viewport": {"width": 1280, "height": 800},
            "ignore_https_errors": req.skip_tls_verification,
        }

        # Add proxy if configured
        if PROXY_URL:
            context_options["proxy"] = {"server": PROXY_URL}

        # Create context and page
        context = await browser.new_context(**context_options)

        # Set up resource blocking
        await context.route("**/*", block_resources)

        # Add custom headers if provided
        if req.headers:
            await context.set_extra_http_headers(req.headers)

        page = await context.new_page()

        try:
            logger.info(f"Scraping {req.url} (active: {page_semaphore.active})")
            result = await scrape_page(
                page=page,
                url=req.url,
                wait_after_load=req.wait_after_load,
                timeout=req.timeout,
                check_selector=req.check_selector,
            )
            return result
        finally:
            await page.close()
            await context.close()

    finally:
        page_semaphore.release()


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check endpoint."""
    status = "healthy" if browser is not None else "unhealthy"
    return HealthResponse(
        status=status,
        maxConcurrentPages=MAX_CONCURRENT_PAGES,
        activePages=page_semaphore.active,
        availablePages=page_semaphore.available,
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "3000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
