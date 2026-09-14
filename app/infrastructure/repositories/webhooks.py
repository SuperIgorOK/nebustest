from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.errors import PaymentNotFoundError
from app.domain.payment import Payment
from app.infrastructure.models import Payment as PaymentRow
from app.infrastructure.repositories.mapping import to_payment


@dataclass(slots=True)
class SqlAlchemyWebhookRepository:
    sessions: async_sessionmaker[AsyncSession]

    @asynccontextmanager
    async def locked_payment(self, payment_id: UUID) -> AsyncIterator[Payment]:
        # Intentional bounded lock across HTTP delivery; no general-purpose save().
        async with self.sessions() as session, session.begin():
            row = await session.scalar(
                select(PaymentRow).where(PaymentRow.id == payment_id).with_for_update()
            )
            if row is None:
                raise PaymentNotFoundError(str(payment_id))
            payment = to_payment(row)
            yield payment
            row.webhook_attempts = payment.webhook_attempts
            row.webhook_delivered_at = payment.webhook_delivered_at
            row.last_webhook_error = payment.last_webhook_error
