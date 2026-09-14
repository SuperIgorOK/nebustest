"""Replay-safe emulator. A real provider needs its own idempotency contract."""

import asyncio
import hashlib
import random
from uuid import UUID

from app.config import get_settings
from app.domain.payment import PaymentStatus


class MockPaymentGateway:
    async def process(self, payment_id: UUID) -> PaymentStatus:
        settings = get_settings()
        await asyncio.sleep(
            random.uniform(
                settings.payment_processing_min_seconds,
                settings.payment_processing_max_seconds,
            )
        )
        draw = int.from_bytes(hashlib.sha256(str(payment_id).encode()).digest()[:8], "big") / 2**64
        return (
            PaymentStatus.SUCCEEDED
            if draw < settings.payment_success_rate
            else PaymentStatus.FAILED
        )
