"""A crash after publish confirmation can produce a duplicate event."""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.config import get_settings
from app.infrastructure.db import async_session_factory
from app.infrastructure.messaging.broker import create_broker
from app.infrastructure.messaging.publisher import publish_confirmed
from app.infrastructure.messaging.retry import ATTEMPT_HEADER
from app.infrastructure.messaging.topology import (
    PAYMENTS_ROUTING_KEY,
    build_topology,
    declare_topology,
)
from app.infrastructure.models import OutboxEvent, OutboxStatus
from app.logging import setup_logging

logger = logging.getLogger(__name__)


async def publish_batch(broker, topology, *, session_factory=async_session_factory, limit=100):
    published = 0
    async with session_factory() as session:
        async with session.begin():
            events = (
                await session.scalars(
                    select(OutboxEvent)
                    .where(OutboxEvent.status == OutboxStatus.PENDING)
                    .order_by(OutboxEvent.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for event in events:
                try:
                    await publish_confirmed(
                        broker,
                        event.payload,
                        exchange=topology.events_exchange,
                        routing_key=PAYMENTS_ROUTING_KEY,
                        message_id=str(event.id),
                        headers={ATTEMPT_HEADER: 1},
                    )
                except Exception as exc:
                    event.attempts += 1
                    event.last_error = str(exc)
                    logger.warning("outbox_publish_failed", extra={"outbox_id": str(event.id)})
                else:
                    event.status = OutboxStatus.PUBLISHED
                    event.published_at = datetime.now(UTC)
                    event.last_error = None
                    published += 1
    return published


async def main():
    settings = get_settings()
    setup_logging(settings.log_level)
    topology = build_topology(settings)
    async with create_broker(settings) as broker:
        await declare_topology(broker, topology)
        while True:
            try:
                await publish_batch(broker, topology, limit=settings.outbox_batch_size)
            except Exception:
                logger.exception("outbox_iteration_failed")
            await asyncio.sleep(settings.outbox_poll_interval_seconds)


if __name__ == "__main__":
    asyncio.run(main())
