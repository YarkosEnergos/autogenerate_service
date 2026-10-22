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


class GenerateRequest(BaseModel):
    user_id: int = Field(gt=0)
    model_slug: str = Field(min_length=1, max_length=64)
    prompt: str = Field(min_length=1)
    ref_images: list[str] = Field(default_factory=list)


class GenerateResponse(BaseModel):
    task_id: uuid.UUID


class AttemptOut(BaseModel):
    id: uuid.UUID
    provider: str
    priority: int
    status: str
    external_id: str | None
    error_type: str | None
    error_detail: str | None
    result_url: str | None
    late_result: str | None
    started_at: datetime
    deadline_at: datetime
    finished_at: datetime | None


class CurrentLegOut(BaseModel):
    attempt_id: uuid.UUID
    provider: str
    priority: int
    status: str


class TaskOut(BaseModel):
    id: uuid.UUID
    user_id: int
    model_slug: str
    status: str
    price: int
    result_url: str | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    current_leg: CurrentLegOut | None
    attempts: list[AttemptOut]
