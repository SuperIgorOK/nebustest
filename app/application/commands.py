import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.domain.payment import Currency


@dataclass(frozen=True, slots=True)
class CreatePayment:
    amount: Decimal
    currency: Currency
    description: str
    metadata: dict[str, Any]
    webhook_url: str
    idempotency_key: str

    def fingerprint(self) -> str:
        data = {
            "amount": format(self.amount.normalize(), "f"),
            "currency": self.currency.value,
            "description": self.description,
            "metadata": self.metadata,
            "webhook_url": self.webhook_url,
        }
        encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()
