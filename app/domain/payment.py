from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID


class Currency(StrEnum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(slots=True)
class Payment:
    id: UUID
    amount: Decimal
    currency: Currency
    description: str
    metadata: dict[str, Any]
    status: PaymentStatus
    webhook_url: str
    idempotency_key: str
    request_fingerprint: str
    created_at: datetime
    processed_at: datetime | None
    webhook_delivered_at: datetime | None
    webhook_attempts: int
    last_webhook_error: str | None

    @property
    def is_pending(self) -> bool:
        return self.status == PaymentStatus.PENDING

    def webhook_payload(self) -> dict[str, str]:
        if self.is_pending or self.processed_at is None:
            raise ValueError("Cannot notify about an unprocessed payment")
        return {
            "payment_id": str(self.id),
            "status": self.status.value,
            "processed_at": self.processed_at.isoformat(),
        }

    @property
    def webhook_id(self) -> str:
        return f"payment:{self.id}:status-webhook"
