# LightCrawl

Lightweight search & scrape API for AI agents. Deploy in 30 seconds.

```bash
git clone https://github.com/yourname/lightcrawl && cd lightcrawl
./start.sh
```

## Quick Start

```bash
# Start (full: API + MCP + Playwright)
./start.sh

# Start minimal (API only, no MCP/Playwright)
./start.sh --minimal

# Stop
./stop.sh

# Delete (removes all data)
./delete.sh
```

## Features

- **JavaScript rendering** via Playwright (SPA sites, anti-bot bypass)
- **Meta-search** via SearXNG (Google, Bing, DuckDuckGo)
- **Tor proxy** for anonymous searches
- **MCP support** for Claude Desktop, Cursor, etc.
- **Auto-retry** with exponential backoff (DLQ)
- **Per-domain rate limiting** (1 req/sec)
- **User-Agent rotation** (5 realistic browsers)
- **Connection pooling** for performance
- **Page caching** (24h default)

## API

### Search & Scrape

```bash
curl -X POST http://localhost:3002/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "python async programming", "limit": 5}'
```

Response:
```json
{
  "success": true,
  "data": [
    {
      "url": "https://docs.python.org/3/library/asyncio.html",
      "markdown": "# asyncio — Asynchronous I/O\n\nasyncio is a library..."
    }
  ]
}
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | required | Search query |
| `limit` | int | 5 | Max results (1-50) |
| `timeout` | int | 15000 | Timeout in ms |

## Python Integration

### Simple Client

```python
import httpx

class LightCrawl:
    def __init__(self, base_url: str = "http://localhost:3002"):
        self.base_url = base_url
        self.client = httpx.Client(timeout=120)

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """Search and scrape, returns list of {url, markdown}."""
        resp = self.client.post(
            f"{self.base_url}/v1/search",
            json={"query": query, "limit": limit},
        )
        resp.raise_for_status()
        data = resp.json()
        if data["success"]:
            return data["data"]
        raise Exception(data.get("error", "Search failed"))

# Usage
crawler = LightCrawl()
results = crawler.search("python async tutorial", limit=3)
for r in results:
    print(f"URL: {r['url']}")
    print(f"Content: {r['markdown'][:200]}...")
```

### Async Client

```python
import httpx

class AsyncLightCrawl:
    def __init__(self, base_url: str = "http://localhost:3002"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=120)

    async def search(self, query: str, limit: int = 5) -> list[dict]:
        resp = await self.client.post(
            f"{self.base_url}/v1/search",
            json={"query": query, "limit": limit},
        )
        resp.raise_for_status()
        data = resp.json()
        if data["success"]:
            return data["data"]
        raise Exception(data.get("error", "Search failed"))

    async def close(self):
        await self.client.aclose()

# Usage
import asyncio

async def main():
    crawler = AsyncLightCrawl()
    results = await crawler.search("rust vs go performance")
    for r in results:
        print(r["url"])
    await crawler.close()

asyncio.run(main())
```

### With AI Agent (LangChain-style)

```python
from lightcrawl import LightCrawl

def research_topic(topic: str, depth: int = 2) -> str:
    """Multi-step research using LightCrawl."""
    crawler = LightCrawl()
    all_content = []

    # Initial search
    results = crawler.search(topic, limit=5)
    all_content.extend(r["markdown"] for r in results)

    # Follow-up searches based on content
    for i in range(depth - 1):
        # Extract subtopics (simplified - use LLM in real code)
        subtopic = f"{topic} advanced techniques"
        results = crawler.search(subtopic, limit=3)
        all_content.extend(r["markdown"] for r in results)

    return "\n\n---\n\n".join(all_content)

# Usage
research = research_topic("machine learning transformers")
print(f"Collected {len(research)} chars of research")
```

## MCP Integration (Claude Desktop, Cursor)

LightCrawl includes an MCP server for direct integration with LLM applications.

MCP starts automatically with `./start.sh` at `http://localhost:8000/sse`.

### Claude Desktop Config

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "lightcrawl": {
      "url": "http://localhost:8000/sse"
    }
  }
}
```

For remote server, replace `localhost` with your server IP.

### Available Tools

| Tool | Description |
|------|-------------|
| `web_search` | Search web and return full page content as markdown |

**Parameters:**
- `query` — search query (e.g. "python async tutorial")
- `limit` — number of results (1-20, default 5)

**Returns:** List of `{url, markdown}` objects with full page content.

### Example

```
You: Find information about Python async best practices

Claude: [Uses web_search tool with query="python async best practices"]
Found 5 results. Key points:
1. Use asyncio.gather() for concurrent tasks...
```

## Architecture

```
┌─────────┐     ┌─────────────┐     ┌─────────┐
│ Client  │────▶│     API     │────▶│ SearXNG │──▶ Tor ──▶ Google/Bing
└─────────┘     └──────┬──────┘     └─────────┘
                       │
                       ▼
                ┌─────────────┐
                │    Redis    │
                │   (queue)   │
                └──────┬──────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    ┌──────────┐ ┌──────────┐ ┌──────────┐
    │ Worker 1 │ │ Worker 2 │ │ Worker N │
    └──────────┘ └──────────┘ └──────────┘
```

## Configuration

All settings have sensible defaults. Override via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `SEARXNG_RATE_LIMIT` | 30 | Searches per minute |
| `SCRAPE_CONCURRENCY` | 50 | Concurrent scrapes per worker |
| `SCRAPE_TIMEOUT` | 10 | HTTP timeout (seconds) |
| `JOB_TIMEOUT` | 120 | Max wait for results (seconds) |
| `CACHE_TTL_PAGE` | 86400 | Page cache TTL (seconds) |
| `API_KEYS` | (empty) | Comma-separated auth keys |

## Scaling

```bash
# More workers = more throughput
docker compose up -d --scale worker=8
```

## Auth (optional)

```bash
# Set API keys
API_KEYS=key1,key2 ./start.sh

# Use in Python
crawler = LightCrawl()
crawler.client.headers["Authorization"] = "Bearer key1"
```

## Project Structure

```
lightcrawl/
├── services/
│   ├── api/                      # Main API service
│   │   ├── src/
│   │   │   ├── main.py           # FastAPI app
│   │   │   ├── config.py         # Settings
│   │   │   ├── worker.py         # Scrape worker
│   │   │   ├── mcp_server.py     # MCP server for LLMs
│   │   │   ├── redis_client.py   # Redis connections
│   │   │   ├── api/
│   │   │   │   ├── routes.py     # Endpoints
│   │   │   │   ├── schemas.py    # Request/response models
│   │   │   │   └── auth.py       # API key auth
│   │   │   ├── scraper/
│   │   │   │   ├── queue.py      # Job queue + DLQ
│   │   │   │   └── extractor.py  # HTML → Markdown
│   │   │   └── search/
│   │   │       ├── base.py       # Abstract backend
│   │   │       └── searxng.py    # SearXNG implementation
│   │   ├── Dockerfile
│   │   └── pyproject.toml
│   │
│   └── playwright/               # Playwright microservice
│       ├── src/
│       │   └── main.py           # FastAPI + Playwright
│       ├── Dockerfile
│       └── requirements.txt
│
├── config/
│   └── searxng/                  # SearXNG config
│
├── docker-compose.yml
├── start.sh / stop.sh / delete.sh
└── README.md
```
