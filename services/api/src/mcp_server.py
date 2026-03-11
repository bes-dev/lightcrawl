"""
MCP Server for LightCrawl.

Provides web search and scraping tools for LLM applications.
"""
import os
import sys
import httpx
from fastmcp import FastMCP

mcp = FastMCP("LightCrawl")

API_URL = os.getenv("LIGHTCRAWL_API_URL", "http://localhost:3002")
_TIMEOUT = 120


def _api_call(path: str, payload: dict) -> dict:
    with httpx.Client(timeout=_TIMEOUT, base_url=API_URL) as client:
        resp = client.post(path, json=payload)
        resp.raise_for_status()
        data = resp.json()
    if not data.get("success"):
        raise Exception(data.get("error", "API call failed"))
    return data


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    from starlette.responses import PlainTextResponse
    return PlainTextResponse("OK")


@mcp.tool
def lightcrawl_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web and return snippets. Fast, no page fetching.

    Best for: quick fact-checking, getting a list of relevant URLs,
    finding sources before deciding which to read in full.

    Args:
        query: Search query (e.g. "python async tutorial")
        max_results: Number of results (1-20, default 5)

    Returns:
        List of {url, markdown (snippet), title}
    """
    max_results = max(1, min(20, max_results))
    data = _api_call("/v1/search", {"query": query, "limit": max_results, "scrape": False})
    return data["data"]


@mcp.tool
def lightcrawl_extract(query: str, max_results: int = 5) -> list[dict]:
    """Search the web, then fetch and extract full page content as markdown.

    Best for: reading articles, research, getting complete information.
    Slower than lightcrawl_search because it downloads and parses each page.

    Args:
        query: Search query (e.g. "python async tutorial")
        max_results: Number of pages to extract (1-20, default 5)

    Returns:
        List of {url, markdown (full content), title, author, date, description}
    """
    max_results = max(1, min(20, max_results))
    data = _api_call("/v1/search", {"query": query, "limit": max_results, "scrape": True})
    return data["data"]


@mcp.tool
def lightcrawl_scrape(urls: list[str], use_playwright: bool = False) -> list[dict]:
    """Scrape specific URLs and extract content as markdown.

    Best for: extracting content from known URLs, reading specific pages.
    Use use_playwright=True for JavaScript-heavy sites (SPAs, dynamic content).

    Args:
        urls: List of URLs to scrape (1-100)
        use_playwright: Use headless browser for JS rendering (default False)

    Returns:
        List of {url, markdown (full content), title, author, date, description}
    """
    data = _api_call("/v1/scrape", {"urls": urls[:100], "use_playwright": use_playwright})
    return data["data"]


if __name__ == "__main__":
    if "--sse" in sys.argv or "--http" in sys.argv:
        port = 8000
        for i, arg in enumerate(sys.argv):
            if arg == "--port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
        mcp.run(transport="sse", host="0.0.0.0", port=port)
    else:
        mcp.run()
