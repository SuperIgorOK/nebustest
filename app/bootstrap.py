"""Composition root: the only place that connects use cases to concrete adapters."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.payments import PaymentService
from app.application.processing import PaymentProcessor
from app.application.webhooks import WebhookService
from app.config import get_settings
from app.infrastructure.db import async_session_factory
from app.infrastructure.gateway import MockPaymentGateway
from app.infrastructure.http import HttpxWebhookClient
from app.infrastructure.repositories.payments import SqlAlchemyPaymentRepository
from app.infrastructure.repositories.webhooks import SqlAlchemyWebhookRepository


def build_payment_service() -> PaymentService:
    return PaymentService(SqlAlchemyPaymentRepository(async_session_factory))


def build_processor(
    http_client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession] = async_session_factory,
) -> PaymentProcessor:
    return PaymentProcessor(
        repository=SqlAlchemyPaymentRepository(sessions),
        gateway=MockPaymentGateway(),
        webhooks=WebhookService(
            SqlAlchemyWebhookRepository(sessions),
            HttpxWebhookClient(http_client),
            get_settings().message_max_attempts,
        ),
    )
