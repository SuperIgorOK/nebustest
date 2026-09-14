from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.auth import get_idempotency_key, verify_api_key
from app.api.schemas import PaymentAccepted, PaymentCreate, PaymentRead
from app.application.commands import CreatePayment
from app.application.payments import PaymentService
from app.bootstrap import build_payment_service

router = APIRouter(
    prefix="/api/v1/payments", tags=["payments"], dependencies=[Depends(verify_api_key)]
)
Service = Annotated[PaymentService, Depends(build_payment_service)]


@router.post("", response_model=PaymentAccepted, status_code=202)
async def create(
    payload: PaymentCreate,
    service: Service,
    idempotency_key: Annotated[str, Depends(get_idempotency_key)],
) -> PaymentAccepted:
    command = CreatePayment(
        amount=payload.amount,
        currency=payload.currency,
        description=payload.description,
        metadata=payload.metadata,
        webhook_url=str(payload.webhook_url),
        idempotency_key=idempotency_key,
    )
    return PaymentAccepted.from_payment(await service.create(command))


@router.get("/{payment_id}", response_model=PaymentRead)
async def get(payment_id: UUID, service: Service) -> PaymentRead:
    return PaymentRead.from_payment(await service.get(payment_id))
