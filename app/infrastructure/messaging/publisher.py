"""One publication contract for outbox, retries and dead letters."""

from typing import Any

from faststream.rabbit import RabbitBroker, RabbitExchange


async def publish_confirmed(
    broker: RabbitBroker,
    payload: dict[str, Any],
    *,
    exchange: RabbitExchange,
    routing_key: str,
    message_id: str | None,
    headers: dict[str, Any],
) -> None:
    confirmation = await broker.publish(
        payload,
        exchange=exchange,
        routing_key=routing_key,
        message_id=message_id,
        headers=headers,
        persist=True,
        mandatory=True,
        timeout=5,
    )
    if confirmation is False:
        raise RuntimeError("RabbitMQ publish was not confirmed")
