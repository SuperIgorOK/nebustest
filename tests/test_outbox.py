from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.config import Settings
from app.infrastructure.messaging.outbox import publish_batch
from app.infrastructure.messaging.topology import build_topology
from app.infrastructure.models import OutboxEvent
from tests.test_payments import create

pytestmark = pytest.mark.integration


async def test_outbox_retries_failed_publish(session_factory):
    payment = await create(session_factory)
    broker = AsyncMock()
    broker.publish.side_effect = [RuntimeError("offline"), True]
    topology = build_topology(Settings())
    assert await publish_batch(broker, topology, session_factory=session_factory) == 0
    async with session_factory() as session:
        event = await session.scalar(select(OutboxEvent))
        event_id = str(event.id)
        assert event.status == "pending" and event.attempts == 1
    assert await publish_batch(broker, topology, session_factory=session_factory) == 1
    assert await publish_batch(broker, topology, session_factory=session_factory) == 0
    for call in broker.publish.await_args_list:
        assert call.kwargs["message_id"] == event_id
        assert call.args[0] == {"payment_id": str(payment.id)}


async def test_unconfirmed_publish_stays_pending(session_factory):
    await create(session_factory)
    broker = AsyncMock()
    broker.publish.return_value = False
    assert (
        await publish_batch(broker, build_topology(Settings()), session_factory=session_factory)
        == 0
    )
    async with session_factory() as session:
        assert (await session.scalar(select(OutboxEvent))).status == "pending"
