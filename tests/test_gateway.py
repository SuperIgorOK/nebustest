from uuid import uuid4

from app.config import Settings
from app.infrastructure import gateway


async def test_gateway_replay_is_stable(monkeypatch):
    monkeypatch.setattr(
        gateway,
        "get_settings",
        lambda: Settings(PAYMENT_PROCESSING_MIN_SECONDS=0, PAYMENT_PROCESSING_MAX_SECONDS=0),
    )
    payment_id = uuid4()
    assert await gateway.MockPaymentGateway().process(
        payment_id
    ) == await gateway.MockPaymentGateway().process(payment_id)
