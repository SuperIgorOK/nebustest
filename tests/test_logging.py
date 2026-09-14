import json
import logging

import pytest
from httpx import ASGITransport, AsyncClient

from app.logging import JsonFormatter
from app.main import app


def test_json_formatter_includes_structured_extra_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "test-service")
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="payment_created",
        args=(),
        exc_info=None,
    )
    record.event = "payment_created"
    record.payment_id = "payment-1"
    record.message_id = "message-1"
    record.attempt = 2

    payload = json.loads(formatter.format(record))

    assert payload["service"] == "test-service"
    assert payload["event"] == "payment_created"
    assert payload["payment_id"] == "payment-1"
    assert payload["message_id"] == "message-1"
    assert payload["attempt"] == 2


async def test_api_key_value_is_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    secret = "super-secret-api-key"
    caplog.set_level(logging.WARNING)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health", headers={"X-API-Key": secret})

    assert response.status_code == 401
    assert "api_auth_failed" in caplog.text
    assert secret not in caplog.text
