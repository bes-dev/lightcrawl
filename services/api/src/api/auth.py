from fastapi import Request, HTTPException

from src.config import settings


async def verify_api_key(request: Request) -> None:
    if not settings.api_keys_set:
        return

    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth[7:] in settings.api_keys_set:
        return

    raise HTTPException(status_code=401, detail="Invalid API key")
