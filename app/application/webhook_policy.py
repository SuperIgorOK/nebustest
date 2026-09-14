"""Exact-origin policy; configured hostnames and their DNS must be trusted."""

from collections.abc import Iterable
from urllib.parse import urlsplit


def validate_webhook_url(url: str, allowed_origins: Iterable[str]) -> None:
    def origin(value: str) -> tuple[str, str | None, int]:
        parsed = urlsplit(value)
        if parsed.username or parsed.password:
            raise ValueError("Webhook URL must not contain credentials")
        return (
            parsed.scheme,
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )

    if origin(url) not in {origin(value) for value in allowed_origins}:
        raise ValueError("Webhook origin is not allowed")
