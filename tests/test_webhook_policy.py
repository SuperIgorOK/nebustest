import httpx
import pytest
from pydantic import ValidationError

from app.api.schemas import PaymentCreate
from app.application.errors import PermanentInfrastructureError
from app.config import Settings
from app.infrastructure.http import HttpxWebhookClient, validate_webhook_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://169.254.169.254/",
        "http://[::1]/",
        "https://example.com.evil.test/",
        "https://example.com:444/",
        "http://example.com/",
        "https://user:password@example.com/",
    ],
)
def test_api_rejects_untrusted_webhook(url):
    with pytest.raises(ValidationError):
        PaymentCreate(amount="1.00", currency="RUB", description="Test", webhook_url=url)


def test_exact_origin_accepts_paths_and_normalized_port():
    validate_webhook_url("https://example.com:443/hooks/payment?id=1")


def test_empty_allowlist_denies_all(monkeypatch):
    from app.infrastructure import http

    monkeypatch.setattr(http, "get_settings", lambda: Settings(WEBHOOK_ALLOWED_ORIGINS=[]))
    with pytest.raises(ValueError):
        validate_webhook_url("https://example.com/")


async def test_http_client_rechecks_policy_before_network():
    requests = []

    async def handle(request):
        requests.append(request)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(PermanentInfrastructureError):
            await HttpxWebhookClient(client).deliver(
                url="http://127.0.0.1/", payload={}, headers={}
            )
    assert requests == []


async def test_redirect_cannot_bypass_allowlist():
    requests = []

    async def handle(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/internal"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), follow_redirects=True
    ) as client:
        with pytest.raises(PermanentInfrastructureError):
            await HttpxWebhookClient(client).deliver(
                url="https://example.com/hook", payload={}, headers={}
            )
    assert len(requests) == 1
