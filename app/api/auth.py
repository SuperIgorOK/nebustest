import logging
from secrets import compare_digest
from typing import Annotated

from fastapi import Header, HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import get_settings

logger = logging.getLogger(__name__)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    x_api_key: Annotated[str | None, Security(api_key_header)],
) -> None:
    if x_api_key is None or not compare_digest(
        x_api_key.encode("utf-8"), get_settings().api_key.encode("utf-8")
    ):
        logger.warning("api_auth_failed", extra={"event": "api_auth_failed"})
        raise HTTPException(status_code=401, detail="Invalid API key")


async def get_idempotency_key(
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> str:
    normalized = idempotency_key.strip()
    if not 1 <= len(normalized) <= 255:
        raise HTTPException(status_code=422, detail="Idempotency-Key must contain 1–255 characters")
    return normalized
