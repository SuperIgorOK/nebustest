import asyncio
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.config import Settings
from app.infrastructure.messaging.broker import create_broker
from app.infrastructure.messaging.outbox import publish_batch
from app.infrastructure.messaging.retry_router import RabbitRetryRouter
from app.infrastructure.messaging.topology import build_topology, declare_topology
from app.infrastructure.models import OutboxEvent
from tests.test_payments import create

pytestmark = pytest.mark.integration


@pytest.fixture
async def rabbit():
    url = os.getenv("TEST_RABBITMQ_URL")
    if not url:
        pytest.skip("Set TEST_RABBITMQ_URL for RabbitMQ integration tests")
    prefix = "test." + uuid4().hex
    settings = Settings(
        RABBITMQ_URL=url,
        PAYMENTS_QUEUE=prefix,
        PAYMENTS_EXCHANGE=prefix + ".events",
        PAYMENTS_RETRY_EXCHANGE=prefix + ".retry",
        PAYMENTS_DEAD_LETTER_EXCHANGE=prefix + ".dlx",
        PAYMENTS_DEAD_LETTER_QUEUE=prefix + ".dlq",
        RETRY_BASE_DELAY_SECONDS=0.1,
    )
    topology = build_topology(settings)
    async with create_broker(settings) as broker:
        await declare_topology(broker, topology)
        try:
            yield broker, topology, settings
        finally:
            for queue in [
                topology.payments_queue,
                *topology.retry_queues,
                topology.dead_letter_queue,
            ]:
                await (await broker.declare_queue(queue)).delete(if_unused=False, if_empty=False)
            for exchange in [
                topology.events_exchange,
                topology.retry_exchange,
                topology.dead_letter_exchange,
            ]:
                await (await broker.declare_exchange(exchange)).delete(if_unused=False)


async def receive(broker, queue):
    declared = await broker.declare_queue(queue)
    async with asyncio.timeout(5):
        while True:
            message = await declared.get(fail=False)
            if message is not None:
                await message.ack()
                return message
            await asyncio.sleep(0.02)


async def test_real_outbox_retry_and_dlq(session_factory, rabbit):
    broker, topology, settings = rabbit
    payment = await create(session_factory)
    assert await publish_batch(broker, topology, session_factory=session_factory) == 1
    message = await receive(broker, topology.payments_queue)
    assert json.loads(message.body) == {"payment_id": str(payment.id)}
    router = RabbitRetryRouter(broker, topology, settings)
    for attempt in [1, 2]:
        assert message.headers["x-attempt"] == attempt
        assert (
            await router.retry_or_dlq(
                payload=json.loads(message.body),
                current_attempt=attempt,
                message_id=message.message_id,
                reason="test",
            )
            == "retry"
        )
        message = await receive(broker, topology.payments_queue)
    assert message.headers["x-attempt"] == 3
    assert (
        await router.retry_or_dlq(
            payload=json.loads(message.body),
            current_attempt=3,
            message_id=message.message_id,
            reason="test",
        )
        == "dlq"
    )
    dead = await receive(broker, topology.dead_letter_queue)
    assert dead.message_id == message.message_id
    assert dead.headers["x-attempt"] == 3


async def test_unroutable_outbox_stays_pending(session_factory, rabbit):
    broker, topology, _ = rabbit
    await create(session_factory)
    queue = await broker.declare_queue(topology.payments_queue)
    exchange = await broker.declare_exchange(topology.events_exchange)
    await queue.unbind(exchange, routing_key=topology.payments_queue.routing())
    assert await publish_batch(broker, topology, session_factory=session_factory) == 0
    async with session_factory() as session:
        event = await session.scalar(select(OutboxEvent))
        assert event.status == "pending"
        assert event.last_error
