from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str
    limit: int = Field(default=5, ge=1, le=50)
    timeout: int = Field(default=15000, ge=1000, le=120000)  # ms
    scrape: bool = True


class SearchResultItem(BaseModel):
    url: str
    markdown: str
    title: str | None = None
    author: str | None = None
    date: str | None = None
    description: str | None = None


class SearchResponse(BaseModel):
    success: bool
    data: list[SearchResultItem]
    error: str | None = None


class ScrapeRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=100)
    use_playwright: bool = False
    timeout: int = Field(default=30000, ge=1000, le=120000)  # ms
