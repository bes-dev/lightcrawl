from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Redis
    redis_url: str = "redis://redis:6379"

    # SearXNG
    searxng_url: str = "http://searxng:8080"
    searxng_rate_limit: int = 30  # rpm

    # Scraping
    scrape_concurrency: int = 50  # per worker
    scrape_timeout: int = 10
    playwright_url: str = ""  # Optional: http://playwright:3000

    # Job settings
    job_timeout: int = 120  # seconds to wait for all results
    job_poll_interval: float = 0.1  # seconds

    # Cache TTL
    cache_ttl_search: int = 3600
    cache_ttl_page: int = 86400

    # Auth
    api_keys: str = ""

    @property
    def api_keys_set(self) -> set[str]:
        if not self.api_keys:
            return set()
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}

    class Config:
        env_file = ".env"


settings = Settings()
