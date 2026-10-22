import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PaymentWebhook(BaseModel):
    payment_id: str = Field(min_length=1, max_length=128)
    user_id: int = Field(gt=0)
    tokens: int = Field(gt=0)
    status: str


class WebhookAck(BaseModel):
    status: str = "ok"


class LedgerEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: int
    reason: str
    task_id: uuid.UUID | None
    payment_id: str | None
    created_at: datetime


class BalanceOut(BaseModel):
    user_id: int
    balance: int
    ledger: list[LedgerEntryOut]
