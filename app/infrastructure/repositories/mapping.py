from app.domain.payment import Currency, Payment, PaymentStatus
from app.infrastructure.models import Payment as PaymentRow


def to_payment(row: PaymentRow) -> Payment:
    return Payment(
        id=row.id,
        amount=row.amount,
        currency=Currency(row.currency),
        description=row.description,
        metadata=row.metadata_json,
        status=PaymentStatus(row.status),
        webhook_url=row.webhook_url,
        idempotency_key=row.idempotency_key,
        request_fingerprint=row.request_fingerprint,
        created_at=row.created_at,
        processed_at=row.processed_at,
        webhook_delivered_at=row.webhook_delivered_at,
        webhook_attempts=row.webhook_attempts,
        last_webhook_error=row.last_webhook_error,
    )
