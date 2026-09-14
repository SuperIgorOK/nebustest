from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.application.errors import PaymentNotFoundError
from app.application.ports import PaymentGateway, PaymentRepository
from app.application.webhooks import WebhookService
from app.domain.payment import PaymentStatus


@dataclass(slots=True)
class PaymentProcessor:
    repository: PaymentRepository
    gateway: PaymentGateway
    webhooks: WebhookService

    async def process(self, payment_id: UUID) -> None:
        payment = await self.repository.get(payment_id)
        if payment is None:
            raise PaymentNotFoundError(str(payment_id))
        if payment.is_pending:
            # Gateway must be replay-safe: a crash can occur before saving its result.
            result = PaymentStatus(await self.gateway.process(payment_id))
            if result == PaymentStatus.PENDING:
                raise ValueError("Gateway must return a terminal payment status")
            await self.repository.finish_pending(payment_id, result, datetime.now(UTC))
        await self.webhooks.deliver(payment_id)
