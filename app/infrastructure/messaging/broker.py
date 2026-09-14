from faststream.rabbit import Channel, RabbitBroker

from app.config import Settings, get_settings


def create_broker(settings: Settings | None = None) -> RabbitBroker:
    settings = settings or get_settings()
    return RabbitBroker(
        settings.rabbitmq_url,
        default_channel=Channel(prefetch_count=1, publisher_confirms=True, on_return_raises=True),
    )
