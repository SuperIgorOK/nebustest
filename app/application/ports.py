from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.application.commands import CreatePayment
from app.domain.payment import Payment, PaymentStatus


class PaymentRepository(Protocol):
    async def create_or_get(self, command: CreatePayment, fingerprint: str) -> Payment:
        """Atomically insert payment + outbox, or return the winner for the same key."""
        ...

    async def get(self, payment_id: UUID) -> Payment | None: ...

    async def finish_pending(self, payment_id: UUID, status: PaymentStatus, at: datetime) -> None:
        """Only pending payments may transition to a terminal status."""
        ...


class WebhookRepository(Protocol):
    def locked_payment(self, payment_id: UUID) -> AbstractAsyncContextManager[Payment]:
        """Serialize delivery; commit only webhook fields on successful context exit."""
        ...


class PaymentGateway(Protocol):
    async def process(self, payment_id: UUID) -> PaymentStatus: ...


class WebhookSender(Protocol):
    async def deliver(
        self, *, url: str, payload: Mapping[str, object], headers: Mapping[str, str]
    ) -> None: ...
