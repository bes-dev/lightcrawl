from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str
    limit: int = Field(default=5, ge=1, le=50)
    timeout: int = Field(default=15000, ge=1000, le=120000)  # ms


class SearchResultItem(BaseModel):
    url: str
    markdown: str


class SearchResponse(BaseModel):
    success: bool
    data: list[SearchResultItem]
    error: str | None = None
