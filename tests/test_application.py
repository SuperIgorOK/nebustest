from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.application.errors import PaymentNotFoundError, TemporaryInfrastructureError
from app.application.ports import PaymentGateway, PaymentRepository, WebhookSender
from app.application.processing import PaymentProcessor
from app.application.webhooks import WebhookService
from app.domain.payment import Currency, Payment, PaymentStatus


@pytest.fixture
def payment():
    return Payment(
        id=uuid4(),
        amount=Decimal("10.00"),
        currency=Currency.RUB,
        description="Order",
        metadata={},
        status=PaymentStatus.PENDING,
        webhook_url="https://example.com/hook",
        idempotency_key="order-1",
        request_fingerprint="fingerprint",
        created_at=datetime.now(UTC),
        processed_at=None,
        webhook_delivered_at=None,
        webhook_attempts=0,
        last_webhook_error=None,
    )


@pytest.mark.parametrize("status", [PaymentStatus.SUCCEEDED, PaymentStatus.FAILED])
async def test_terminal_payment_only_retries_notification(payment, status):
    payment.status = status
    repository = AsyncMock(spec=PaymentRepository)
    repository.get.return_value = payment
    gateway = AsyncMock(spec=PaymentGateway)
    webhooks = AsyncMock(spec=WebhookService)
    await PaymentProcessor(repository, gateway, webhooks).process(payment.id)
    gateway.process.assert_not_awaited()
    repository.finish_pending.assert_not_awaited()
    webhooks.deliver.assert_awaited_once_with(payment.id)


async def test_gateway_failure_does_not_finish_or_notify(payment):
    repository = AsyncMock(spec=PaymentRepository)
    repository.get.return_value = payment
    gateway = AsyncMock(spec=PaymentGateway)
    gateway.process.side_effect = TemporaryInfrastructureError("unavailable")
    webhooks = AsyncMock(spec=WebhookService)
    with pytest.raises(TemporaryInfrastructureError):
        await PaymentProcessor(repository, gateway, webhooks).process(payment.id)
    repository.finish_pending.assert_not_awaited()
    webhooks.deliver.assert_not_awaited()


async def test_missing_payment_does_not_call_external_services():
    repository = AsyncMock(spec=PaymentRepository)
    repository.get.return_value = None
    gateway = AsyncMock(spec=PaymentGateway)
    webhooks = AsyncMock(spec=WebhookService)
    with pytest.raises(PaymentNotFoundError):
        await PaymentProcessor(repository, gateway, webhooks).process(uuid4())
    gateway.process.assert_not_awaited()
    webhooks.deliver.assert_not_awaited()


async def test_delivery_error_leaves_transaction_normally_before_retry(payment):
    payment.status = PaymentStatus.SUCCEEDED
    payment.processed_at = datetime.now(UTC)
    committed = []

    class Repository:
        @asynccontextmanager
        async def locked_payment(self, payment_id):
            assert payment_id == payment.id
            yield payment
            committed.append((payment.webhook_attempts, payment.last_webhook_error))

    sender = AsyncMock(spec=WebhookSender)
    sender.deliver.side_effect = TemporaryInfrastructureError("timeout")
    with pytest.raises(TemporaryInfrastructureError, match="timeout"):
        await WebhookService(Repository(), sender).deliver(payment.id)
    assert committed == [(1, "timeout")]
    assert payment.webhook_delivered_at is None
