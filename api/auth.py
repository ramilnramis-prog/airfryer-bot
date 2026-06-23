"""Проверка X-API-Key. Иначе 401."""
from fastapi import Header, HTTPException
from .config import API_KEY


async def require_api_key(x_api_key: str = Header(default="")):
    if not API_KEY or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
    return True
