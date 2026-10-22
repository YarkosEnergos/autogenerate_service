from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.api.deps import get_container, read_signed_body
from app.api.schemas import PaymentWebhook, ProviderWebhook, WebhookAck
from app.container import Container
from app.domain.enums import ErrorType
from app.services.payments import PaymentEvent
from app.services.tasks import ProviderResult

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/providers/{name}", response_model=WebhookAck)
async def provider_webhook(
    name: str,
    request: Request,
    background_tasks: BackgroundTasks,
    container: Container = Depends(get_container),
) -> WebhookAck:
    payload = await read_signed_body(request, ProviderWebhook)
    result = ProviderResult(
        client_ref=payload.client_ref,
        external_id=payload.external_id,
        completed=payload.status == "completed",
        result_url=payload.result_url,
        error_type=ErrorType(payload.error_type) if payload.error_type else None,
        detail=payload.detail,
    )
    next_attempt_id = await container.tasks.apply_result(name, result)
    if next_attempt_id is not None:
        background_tasks.add_task(container.dispatcher.dispatch, next_attempt_id)
    return WebhookAck()


@router.post("/payments", response_model=WebhookAck)
async def payment_webhook(request: Request, container: Container = Depends(get_container)) -> WebhookAck:
    payload = await read_signed_body(request, PaymentWebhook)
    await container.payments.process(PaymentEvent(**payload.model_dump()))
    return WebhookAck()
