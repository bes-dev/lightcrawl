"""
MCP Server for LightCrawl.

Provides web search tool for LLM applications.
"""
import os
import sys
import httpx
from fastmcp import FastMCP

mcp = FastMCP("LightCrawl")

API_URL = os.getenv("LIGHTCRAWL_API_URL", "http://localhost:3002")


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    from starlette.responses import PlainTextResponse
    return PlainTextResponse("OK")


@mcp.tool
def web_search(query: str, limit: int = 5) -> list[dict]:
    """
    Search the web and return page content as markdown.

    Use this tool to find information on any topic. Returns actual page
    content (not just snippets), extracted as clean markdown.

    Args:
        query: Search query (e.g. "python async tutorial", "latest news about AI")
        limit: Number of results to return (1-20, default 5)

    Returns:
        List of results, each containing:
        - url: Source URL
        - markdown: Full page content as markdown
    """
    limit = max(1, min(20, limit))  # Clamp to 1-20

    with httpx.Client(timeout=120, base_url=API_URL) as client:
        resp = client.post("/v1/search", json={"query": query, "limit": limit})
        resp.raise_for_status()
        data = resp.json()

    if not data.get("success"):
        raise Exception(data.get("error", "Search failed"))

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
