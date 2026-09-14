from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.commands import CreatePayment
from app.domain.payment import Payment, PaymentStatus
from app.infrastructure.models import OutboxEvent
from app.infrastructure.models import Payment as PaymentRow
from app.infrastructure.repositories.mapping import to_payment


@dataclass(slots=True)
class SqlAlchemyPaymentRepository:
    sessions: async_sessionmaker[AsyncSession]

    async def create_or_get(self, command: CreatePayment, fingerprint: str) -> Payment:
        query = select(PaymentRow).where(PaymentRow.idempotency_key == command.idempotency_key)
        async with self.sessions() as session:
            try:
                async with session.begin():
                    row = await session.scalar(query)
                    if row is None:
                        row = PaymentRow(
                            amount=command.amount,
                            currency=command.currency.value,
                            description=command.description,
                            metadata_json=command.metadata,
                            webhook_url=command.webhook_url,
                            idempotency_key=command.idempotency_key,
                            request_fingerprint=fingerprint,
                        )
                        session.add(row)
                        await session.flush()
                        session.add(
                            OutboxEvent(
                                event_type="payments.new",
                                aggregate_type="payment",
                                aggregate_id=row.id,
                                payload={"payment_id": str(row.id)},
                            )
                        )
            except IntegrityError:
                # A concurrent request can win the unique-key INSERT.
                # Read after rollback; propagate unrelated constraint failures.
                async with session.begin():
                    row = await session.scalar(query)
                    if row is None:
                        raise
            return to_payment(row)

    async def get(self, payment_id: UUID) -> Payment | None:
        async with self.sessions() as session:
            row = await session.get(PaymentRow, payment_id)
            return to_payment(row) if row is not None else None

    async def finish_pending(self, payment_id: UUID, status: PaymentStatus, at: datetime) -> None:
        async with self.sessions() as session, session.begin():
            await session.execute(
                update(PaymentRow)
                .where(PaymentRow.id == payment_id, PaymentRow.status == PaymentStatus.PENDING)
                .values(status=status.value, processed_at=at)
            )
