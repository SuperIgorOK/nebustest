from dataclasses import dataclass
from uuid import UUID

from app.application.commands import CreatePayment
from app.application.errors import IdempotencyConflictError, PaymentNotFoundError
from app.application.ports import PaymentRepository
from app.domain.payment import Payment


@dataclass(slots=True)
class PaymentService:
    repository: PaymentRepository

    async def create(self, command: CreatePayment) -> Payment:
        fingerprint = command.fingerprint()
        payment = await self.repository.create_or_get(command, fingerprint)
        if payment.request_fingerprint != fingerprint:
            raise IdempotencyConflictError()
        return payment

    async def get(self, payment_id: UUID) -> Payment:
        payment = await self.repository.get(payment_id)
        if payment is None:
            raise PaymentNotFoundError(str(payment_id))
        return payment
