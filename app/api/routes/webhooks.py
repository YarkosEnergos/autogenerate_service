from fastapi import APIRouter, Depends, Request

from app.api.deps import get_container, read_signed_body
from app.api.schemas import PaymentWebhook, WebhookAck
from app.container import Container
from app.services.payments import PaymentEvent

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/payments", response_model=WebhookAck)
async def payment_webhook(request: Request, container: Container = Depends(get_container)) -> WebhookAck:
    payload = await read_signed_body(request, PaymentWebhook)
    await container.payments.process(PaymentEvent(**payload.model_dump()))
    return WebhookAck()
