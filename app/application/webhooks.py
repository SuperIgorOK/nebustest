from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.application.errors import PermanentInfrastructureError
from app.application.ports import WebhookRepository, WebhookSender


@dataclass(slots=True)
class WebhookService:
    repository: WebhookRepository
    sender: WebhookSender
    max_attempts: int = 3

    async def deliver(self, payment_id: UUID) -> None:
        error = None
        async with self.repository.locked_payment(payment_id) as payment:
            if payment.webhook_delivered_at is not None:
                return
            payload = payment.webhook_payload()
            if payment.webhook_attempts >= self.max_attempts:
                raise PermanentInfrastructureError("Webhook attempts exhausted")
            payment.webhook_attempts += 1
            try:
                await self.sender.deliver(
                    url=payment.webhook_url,
                    payload=payload,
                    headers={"X-Webhook-Id": payment.webhook_id},
                )
            except Exception as exc:
                error = exc
                payment.last_webhook_error = str(exc)
            else:
                payment.webhook_delivered_at = datetime.now(UTC)
                payment.last_webhook_error = None
        # The delivery outcome is committed before the consumer schedules a retry.
        if error is not None:
            raise error
