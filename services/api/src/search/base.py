from abc import ABC, abstractmethod


class RateLimitExceeded(Exception):
    """Raised when search rate limit is exceeded."""
    pass


class SearchBackend(ABC):
    """Abstract base for search backends.

    Implementations: SearXNG (free), SerpAPI (paid), Google CSE (paid), etc.
    """

    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> list[str]:
        """Search and return list of URLs."""
        pass

    async def close(self) -> None:
        """Cleanup resources."""
        pass
