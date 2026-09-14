from uuid import uuid4

import httpx
import pytest

from app.application.errors import (
    PermanentInfrastructureError,
    TemporaryInfrastructureError,
)
from app.config import Settings
from app.infrastructure.http import HttpxWebhookClient
from app.infrastructure.messaging.retry import ATTEMPT_HEADER, RetryPolicy, parse_attempt
from app.infrastructure.messaging.retry_router import RabbitRetryRouter
from app.infrastructure.messaging.topology import build_topology


class FakeBroker:
    def __init__(self) -> None:
        self.published: list[dict] = []

    async def publish(self, message=None, **kwargs):
        self.published.append({"message": message, **kwargs})
        return True


def settings() -> Settings:
    return Settings(
        MESSAGE_MAX_ATTEMPTS=3,
        RETRY_BASE_DELAY_SECONDS=2,
        API_KEY="change-me",
    )


def test_retry_policy_uses_exponential_delays_and_attempt_limit() -> None:
    policy = RetryPolicy(max_attempts=3, base_delay_seconds=2)

    first = policy.decide(1)
    second = policy.decide(2)
    third = policy.decide(3)

    assert first.retry is True
    assert first.next_attempt == 2
    assert first.delay_seconds == 2
    assert second.retry is True
    assert second.next_attempt == 3
    assert second.delay_seconds == 4
    assert third.retry is False


def test_parse_attempt_defaults_to_first_attempt() -> None:
    assert parse_attempt(None) == 1
    assert parse_attempt({}) == 1
    assert parse_attempt({ATTEMPT_HEADER: "bad"}) == 1
    assert parse_attempt({ATTEMPT_HEADER: 2}) == 2


async def test_retry_router_sends_attempt_two_to_retry_queue() -> None:
    current_settings = settings()
    broker = FakeBroker()
    topology = build_topology(current_settings)
    router = RabbitRetryRouter(broker=broker, topology=topology, settings=current_settings)

    route = await router.retry_or_dlq(
        payload={"payment_id": str(uuid4())},
        current_attempt=1,
        message_id="message-1",
        reason="timeout",
    )

    published = broker.published[0]
    assert route == "retry"
    assert published["routing_key"] == "payments.new.retry.2"
    assert published["headers"][ATTEMPT_HEADER] == 2
    assert published["headers"]["x-original-message-id"] == "message-1"


async def test_retry_router_sends_attempt_three_to_second_retry_queue() -> None:
    current_settings = settings()
    broker = FakeBroker()
    topology = build_topology(current_settings)
    router = RabbitRetryRouter(broker=broker, topology=topology, settings=current_settings)

    route = await router.retry_or_dlq(
        payload={"payment_id": str(uuid4())},
        current_attempt=2,
        message_id="message-1",
        reason="timeout again",
    )

    published = broker.published[0]
    assert route == "retry"
    assert published["routing_key"] == "payments.new.retry.3"
    assert published["headers"][ATTEMPT_HEADER] == 3
    assert published["headers"]["x-error"] == "timeout again"


async def test_retry_router_sends_third_failure_to_dlq() -> None:
    current_settings = settings()
    broker = FakeBroker()
    topology = build_topology(current_settings)
    router = RabbitRetryRouter(broker=broker, topology=topology, settings=current_settings)

    route = await router.retry_or_dlq(
        payload={"payment_id": str(uuid4())},
        current_attempt=3,
        message_id="message-1",
        reason="timeout",
    )

    published = broker.published[0]
    assert route == "dlq"
    assert published["routing_key"] == current_settings.payments_dead_letter_queue
    assert published["headers"][ATTEMPT_HEADER] == 3


async def test_retry_router_caps_excessive_attempt_in_dlq_headers() -> None:
    current_settings = settings()
    broker = FakeBroker()
    topology = build_topology(current_settings)
    router = RabbitRetryRouter(broker=broker, topology=topology, settings=current_settings)

    route = await router.retry_or_dlq(
        payload={"payment_id": str(uuid4())},
        current_attempt=99,
        message_id="message-1",
        reason="timeout",
    )

    assert route == "dlq"
    assert broker.published[0]["headers"][ATTEMPT_HEADER] == current_settings.message_max_attempts


async def test_http_webhook_client_accepts_2xx() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Webhook-Id"] == "delivery-1"
        assert request.headers["Content-Type"] == "application/json"
        assert request.content == b'{"payment_id":"payment-1","status":"succeeded"}'
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        webhook = HttpxWebhookClient(client)
        await webhook.deliver(
            url="https://example.com/webhooks/payments",
            payload={"payment_id": "payment-1", "status": "succeeded"},
            headers={"X-Webhook-Id": "delivery-1"},
        )


@pytest.mark.parametrize("status_code", [408, 429, 500])
async def test_http_webhook_client_maps_retryable_statuses(status_code: int) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        webhook = HttpxWebhookClient(client)
        with pytest.raises(TemporaryInfrastructureError):
            await webhook.deliver(url="https://example.com", payload={}, headers={})


async def test_http_webhook_client_maps_permanent_statuses() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        webhook = HttpxWebhookClient(client)
        with pytest.raises(PermanentInfrastructureError):
            await webhook.deliver(url="https://example.com", payload={}, headers={})


def test_topology_contains_durable_retry_and_dlq_queues() -> None:
    current_settings = settings()
    topology = build_topology(current_settings)

    assert topology.payments_queue.durable is True
    assert len(topology.retry_queues) == 2
    assert topology.retry_queues[0].arguments["x-message-ttl"] == 2000
    assert topology.retry_queues[1].arguments["x-message-ttl"] == 4000
    assert topology.dead_letter_queue.name == current_settings.payments_dead_letter_queue
