from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.application.payments import PaymentService
from app.bootstrap import build_payment_service
from app.domain.payment import Currency, PaymentStatus
from app.infrastructure.repositories.payments import SqlAlchemyPaymentRepository
from app.main import app

pytestmark = pytest.mark.integration


@pytest.fixture
async def api_client(session_factory):
    app.dependency_overrides[build_payment_service] = lambda: PaymentService(
        SqlAlchemyPaymentRepository(session_factory)
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, None
    finally:
        app.dependency_overrides.clear()


def payment_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "amount": "1250.50",
        "currency": "RUB",
        "description": "Order 42",
        "metadata": {"order_id": "42"},
        "webhook_url": "https://example.com/webhooks/payments",
    }
    payload.update(overrides)
    return payload


def auth_headers(**overrides: str) -> dict[str, str]:
    headers = {
        "X-API-Key": "change-me",
        "Idempotency-Key": "idem-key",
    }
    headers.update(overrides)
    return headers


async def test_create_payment_returns_202_and_contract(
    api_client: tuple[AsyncClient, object],
) -> None:
    client, store = api_client

    response = await client.post(
        "/api/v1/payments",
        json=payment_payload(),
        headers=auth_headers(),
    )

    body = response.json()
    assert response.status_code == 202
    assert UUID(body["payment_id"])
    assert body["status"] == PaymentStatus.PENDING.value
    assert body["created_at"] is not None


@pytest.mark.parametrize(
    ("method", "url", "json"),
    [
        ("get", "/health", None),
        ("post", "/api/v1/payments", payment_payload()),
        ("get", f"/api/v1/payments/{uuid4()}", None),
    ],
)
async def test_x_api_key_is_required_for_all_endpoints(
    api_client: tuple[AsyncClient, object],
    method: str,
    url: str,
    json: dict[str, Any] | None,
) -> None:
    client, _ = api_client
    headers = {"Idempotency-Key": "idem-key"} if method == "post" else {}

    response = await client.request(method, url, json=json, headers=headers)

    assert response.status_code == 401


async def test_invalid_api_key_is_rejected(
    api_client: tuple[AsyncClient, object],
) -> None:
    client, _ = api_client

    response = await client.post(
        "/api/v1/payments",
        json=payment_payload(),
        headers=auth_headers(**{"X-API-Key": "wrong"}),
    )

    assert response.status_code == 401


async def test_idempotency_key_is_required(
    api_client: tuple[AsyncClient, object],
) -> None:
    client, _ = api_client

    response = await client.post(
        "/api/v1/payments",
        json=payment_payload(),
        headers={"X-API-Key": "change-me"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("idempotency_key", ["", "   ", "x" * 256])
async def test_invalid_idempotency_key_is_rejected(
    api_client: tuple[AsyncClient, object],
    idempotency_key: str,
) -> None:
    client, _ = api_client

    response = await client.post(
        "/api/v1/payments",
        json=payment_payload(),
        headers=auth_headers(**{"Idempotency-Key": idempotency_key}),
    )

    assert response.status_code == 422


async def test_same_idempotency_key_and_payload_returns_same_payment_id(
    api_client: tuple[AsyncClient, object],
) -> None:
    client, store = api_client

    first = await client.post(
        "/api/v1/payments",
        json=payment_payload(),
        headers=auth_headers(),
    )
    second = await client.post(
        "/api/v1/payments",
        json=payment_payload(),
        headers=auth_headers(),
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["payment_id"] == first.json()["payment_id"]


async def test_same_idempotency_key_with_different_payload_returns_409(
    api_client: tuple[AsyncClient, object],
) -> None:
    client, store = api_client
    await client.post(
        "/api/v1/payments",
        json=payment_payload(amount="1250.50"),
        headers=auth_headers(),
    )

    response = await client.post(
        "/api/v1/payments",
        json=payment_payload(amount="1251.00"),
        headers=auth_headers(),
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Idempotency key was reused with another payload"}


async def test_get_payment_success(
    api_client: tuple[AsyncClient, object],
) -> None:
    client, _ = api_client
    created = await client.post(
        "/api/v1/payments",
        json=payment_payload(),
        headers=auth_headers(),
    )
    payment_id = created.json()["payment_id"]

    response = await client.get(
        f"/api/v1/payments/{payment_id}",
        headers={"X-API-Key": "change-me"},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["id"] == payment_id
    assert body["amount"] == "1250.50"
    assert body["currency"] == Currency.RUB.value
    assert body["metadata"] == {"order_id": "42"}
    assert body["webhook_attempts"] == 0


async def test_get_payment_not_found(api_client: tuple[AsyncClient, object]) -> None:
    client, _ = api_client

    response = await client.get(
        f"/api/v1/payments/{uuid4()}",
        headers={"X-API-Key": "change-me"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Payment not found"}


async def test_get_payment_invalid_uuid(api_client: tuple[AsyncClient, object]) -> None:
    client, _ = api_client

    response = await client.get(
        "/api/v1/payments/not-a-uuid",
        headers={"X-API-Key": "change-me"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        payment_payload(amount="0"),
        payment_payload(amount="-1"),
        payment_payload(currency="GBP"),
        payment_payload(description=""),
        payment_payload(description=" "),
        payment_payload(description="x" * 501),
        payment_payload(metadata=["not", "object"]),
        payment_payload(webhook_url="ftp://example.com/hook"),
        payment_payload(webhook_url="not-a-url"),
    ],
)
async def test_create_payment_validation_errors(
    api_client: tuple[AsyncClient, object],
    payload: dict[str, Any],
) -> None:
    client, _ = api_client

    response = await client.post(
        "/api/v1/payments",
        json=payload,
        headers=auth_headers(),
    )

    assert response.status_code == 422


async def test_endpoint_does_not_call_publisher(
    api_client: tuple[AsyncClient, object],
) -> None:
    client, store = api_client

    response = await client.post(
        "/api/v1/payments",
        json=payment_payload(),
        headers=auth_headers(),
    )

    assert response.status_code == 202


async def test_openapi_documents_required_headers(
    api_client: tuple[AsyncClient, object],
) -> None:
    client, _ = api_client
    app.openapi_schema = None

    response = await client.get("/openapi.json")
    schema = response.json()

    operation = schema["paths"]["/api/v1/payments"]["post"]
    headers = {
        parameter["name"]: parameter
        for parameter in operation["parameters"]
        if parameter["in"] == "header"
    }
    assert operation["security"] == [{"APIKeyHeader": []}]
    assert schema["components"]["securitySchemes"]["APIKeyHeader"]["name"] == "X-API-Key"
    assert headers["Idempotency-Key"]["required"] is True

    payment_create = schema["components"]["schemas"]["PaymentCreate"]
    webhook_url = payment_create["properties"]["webhook_url"]
    assert "webhook_url" in payment_create["required"]
    assert webhook_url["examples"] == ["http://webhook-echo:9000/webhooks/payments"]
