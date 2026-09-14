import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass

import httpx

from app.application.errors import PermanentInfrastructureError, TemporaryInfrastructureError
from app.application.webhook_policy import validate_webhook_url as check_webhook_url
from app.config import get_settings

logger = logging.getLogger(__name__)


def validate_webhook_url(url: str) -> None:
    check_webhook_url(url, map(str, get_settings().webhook_allowed_origins))


@dataclass(slots=True)
class HttpxWebhookClient:
    client: httpx.AsyncClient

    async def deliver(
        self,
        *,
        url: str,
        payload: Mapping[str, object],
        headers: Mapping[str, str],
    ) -> None:
        try:
            validate_webhook_url(url)
        except ValueError as exc:
            raise PermanentInfrastructureError(str(exc)) from exc
        try:
            async with asyncio.timeout(get_settings().webhook_timeout_seconds):
                response = await self.client.post(
                    url, json=payload, headers=headers, follow_redirects=False
                )
        except (TimeoutError, httpx.RequestError) as exc:
            logger.warning(
                "webhook_http_failed",
                extra={"event": "webhook_http_failed", "reason": str(exc)},
            )
            raise TemporaryInfrastructureError(str(exc)) from exc

        logger.info(
            "webhook_http_response_received",
            extra={"event": "webhook_http_response_received", "status_code": response.status_code},
        )
        classify_webhook_status(response.status_code)


def classify_webhook_status(status_code: int) -> None:
    if 200 <= status_code < 300:
        return
    if status_code in {408, 429} or status_code >= 500:
        raise TemporaryInfrastructureError(f"Webhook delivery failed with HTTP {status_code}")
    raise PermanentInfrastructureError(f"Webhook delivery failed with HTTP {status_code}")
