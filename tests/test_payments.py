import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.schemas import PaymentCreate
from app.application.commands import CreatePayment
from app.application.errors import (
    IdempotencyConflictError,
    PermanentInfrastructureError,
    TemporaryInfrastructureError,
)
from app.application.payments import PaymentService
from app.application.processing import PaymentProcessor
from app.application.webhooks import WebhookService
from app.infrastructure.models import OutboxEvent, Payment
from app.infrastructure.repositories.payments import SqlAlchemyPaymentRepository
from app.infrastructure.repositories.webhooks import SqlAlchemyWebhookRepository

pytestmark = pytest.mark.integration


def payload(**overrides):
    return PaymentCreate.model_validate(
        {
            "amount": "10.50",
            "currency": "RUB",
            "description": "Order",
            "metadata": {"id": 1},
            "webhook_url": "https://example.com/hook",
            **overrides,
        }
    )


async def create(factory, key="key", **overrides):
    data = payload(**overrides)
    command = CreatePayment(
        **data.model_dump(exclude={"webhook_url"}),
        webhook_url=str(data.webhook_url),
        idempotency_key=key,
    )
    return await PaymentService(SqlAlchemyPaymentRepository(factory)).create(command)


async def process_payment(payment_id, *, session_factory, gateway, webhook_client):
    service = PaymentProcessor(
        SqlAlchemyPaymentRepository(session_factory),
        SimpleNamespace(process=gateway),
        WebhookService(SqlAlchemyWebhookRepository(session_factory), webhook_client),
    )
    await service.process(payment_id)


async def deliver_webhook(payment_id, *, session_factory, client):
    await WebhookService(SqlAlchemyWebhookRepository(session_factory), client).deliver(payment_id)


async def test_concurrent_idempotency(session_factory):
    results = await asyncio.gather(*(create(session_factory) for _ in range(8)))
    assert len({p.id for p in results}) == 1
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Payment)) == 1
        assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 1


async def test_conflict_and_decimal_normalization(session_factory):
    first = await create(session_factory)
    same = await create(session_factory, amount="10.500")
    assert same.id == first.id
    with pytest.raises(IdempotencyConflictError):
        await create(session_factory, amount="11.00")


async def test_payment_rolls_back_when_outbox_insert_fails(session_factory):
    from sqlalchemy import text

    async with session_factory() as session, session.begin():
        await session.execute(text("ALTER TABLE outbox ADD CONSTRAINT force_failure CHECK (false)"))
    with pytest.raises(IntegrityError):
        await create(session_factory)
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Payment)) == 0


@pytest.mark.parametrize("status", ["succeeded", "failed"])
async def test_processing_and_replay(session_factory, status):
    payment = await create(session_factory)
    gateway = AsyncMock(return_value=status)
    client = AsyncMock()
    for _ in range(2):
        await process_payment(
            payment.id, session_factory=session_factory, gateway=gateway, webhook_client=client
        )
    gateway.assert_awaited_once()
    client.deliver.assert_awaited_once()
    async with session_factory() as session:
        stored = await session.get(Payment, payment.id)
        assert stored.status == status
        assert stored.processed_at and stored.webhook_delivered_at
        assert stored.webhook_attempts == 1


async def test_webhook_failure_does_not_repeat_gateway(session_factory):
    payment = await create(session_factory)
    gateway = AsyncMock(return_value="succeeded")
    client = AsyncMock()
    client.deliver.side_effect = [TemporaryInfrastructureError("timeout"), None]
    with pytest.raises(TemporaryInfrastructureError):
        await process_payment(
            payment.id, session_factory=session_factory, gateway=gateway, webhook_client=client
        )
    await process_payment(
        payment.id, session_factory=session_factory, gateway=gateway, webhook_client=client
    )
    gateway.assert_awaited_once()
    async with session_factory() as session:
        stored = await session.get(Payment, payment.id)
        assert stored.status == "succeeded"
        assert stored.webhook_attempts == 2
        assert stored.last_webhook_error is None


async def test_duplicate_messages_cannot_reset_webhook_limit(session_factory):
    payment = await create(session_factory)
    client = AsyncMock()
    client.deliver.side_effect = TemporaryInfrastructureError("timeout")
    gateway = AsyncMock(return_value="succeeded")
    for _ in range(3):
        with pytest.raises(TemporaryInfrastructureError):
            await process_payment(
                payment.id, session_factory=session_factory, gateway=gateway, webhook_client=client
            )
    with pytest.raises(PermanentInfrastructureError, match="exhausted"):
        await process_payment(
            payment.id, session_factory=session_factory, gateway=gateway, webhook_client=client
        )
    assert client.deliver.await_count == 3
    gateway.assert_awaited_once()


async def test_concurrent_webhooks_are_serialized(session_factory):
    payment = await create(session_factory)
    async with session_factory() as session, session.begin():
        from datetime import UTC, datetime

        stored = await session.get(Payment, payment.id)
        stored.status = "succeeded"
        stored.processed_at = datetime.now(UTC)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def send(**kwargs):
        entered.set()
        await release.wait()

    client = AsyncMock()
    client.deliver.side_effect = send
    first = asyncio.create_task(
        deliver_webhook(payment.id, session_factory=session_factory, client=client)
    )
    await asyncio.wait_for(entered.wait(), timeout=3)
    second = asyncio.create_task(
        deliver_webhook(payment.id, session_factory=session_factory, client=client)
    )
    release.set()
    await asyncio.gather(first, second)
    client.deliver.assert_awaited_once()
    async with session_factory() as session:
        stored = await session.get(Payment, payment.id)
        assert stored.webhook_delivered_at
        assert stored.webhook_attempts == 1
