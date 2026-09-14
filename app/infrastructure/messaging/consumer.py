import asyncio
import logging
from typing import Any
from uuid import UUID

import httpx
from faststream import FastStream
from faststream.middlewares.acknowledgement.config import AckPolicy
from faststream.rabbit import RabbitMessage
from pydantic import BaseModel, ValidationError

from app.application.errors import (
    PaymentNotFoundError,
    PermanentInfrastructureError,
)
from app.application.processing import PaymentProcessor
from app.bootstrap import build_processor
from app.config import get_settings
from app.infrastructure.messaging.broker import create_broker
from app.infrastructure.messaging.retry import parse_attempt
from app.infrastructure.messaging.retry_router import RabbitRetryRouter
from app.infrastructure.messaging.topology import build_topology, declare_topology
from app.logging import setup_logging

logger = logging.getLogger(__name__)

settings = get_settings()
broker = create_broker(settings)
topology = build_topology(settings)
_http_client: httpx.AsyncClient | None = None
_processor: PaymentProcessor | None = None


class PaymentMessage(BaseModel):
    payment_id: UUID


async def on_startup() -> None:
    global _http_client, _processor
    setup_logging(settings.log_level)
    await broker.connect()
    await declare_topology(broker, topology)
    _http_client = httpx.AsyncClient(timeout=settings.webhook_timeout_seconds)
    _processor = build_processor(_http_client)


async def on_shutdown() -> None:
    global _http_client, _processor
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
    _processor = None


async def process(payment_id: UUID) -> None:
    if _processor is None:
        raise RuntimeError("Consumer dependencies are not initialized")
    await _processor.process(payment_id)


def extract_message_metadata(message: RabbitMessage) -> tuple[dict[str, object], str | None]:
    raw_message = getattr(message, "raw_message", None)
    headers = getattr(raw_message, "headers", None) or {}
    message_id = getattr(raw_message, "message_id", None)
    return dict(headers), message_id


def normalize_payload(payload: Any) -> dict[str, object]:
    if isinstance(payload, dict):
        return payload
    return {"malformed_payload": repr(payload)}


@broker.subscriber(
    topology.payments_queue,
    topology.events_exchange,
    ack_policy=AckPolicy.MANUAL,
)
async def handle_payment_message(payload: Any, message: RabbitMessage) -> None:
    headers, message_id = extract_message_metadata(message)
    attempt = parse_attempt(headers)
    router = RabbitRetryRouter(broker=broker, topology=topology, settings=settings)
    error = None
    permanent = False
    try:
        event = PaymentMessage.model_validate(payload)
    except ValidationError:
        error = "malformed payment message"
        permanent = True
    else:
        try:
            await process(event.payment_id)
        except (PermanentInfrastructureError, PaymentNotFoundError) as exc:
            error, permanent = str(exc), True
        except Exception as exc:
            error = str(exc)
            logger.exception("payment_processing_failed", extra={"message_id": message_id})

    try:
        if error is not None:
            arguments = dict(
                payload=normalize_payload(payload),
                current_attempt=attempt,
                message_id=message_id,
                reason=error,
            )
            if permanent:
                await router.send_to_dlq(**arguments)
            else:
                await router.retry_or_dlq(**arguments)
        await message.ack()
    except Exception:
        # If the next queue did not confirm publication, retain the original.
        await asyncio.sleep(settings.broker_retry_delay_seconds)
        await message.nack(requeue=True)
        raise


app = FastStream(
    broker,
    on_startup=[on_startup],
    on_shutdown=[on_shutdown],
)
