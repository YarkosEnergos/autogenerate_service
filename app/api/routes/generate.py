from fastapi import APIRouter, BackgroundTasks, Depends, status

from app.api.deps import get_container
from app.api.schemas import GenerateRequest, GenerateResponse
from app.container import Container
from app.services.tasks import GenerateCommand

router = APIRouter(tags=["generation"])


@router.post("/generate", response_model=GenerateResponse, status_code=status.HTTP_202_ACCEPTED)
async def generate(
    request: GenerateRequest,
    background_tasks: BackgroundTasks,
    container: Container = Depends(get_container),
) -> GenerateResponse:
    created = await container.tasks.create(GenerateCommand(**request.model_dump()))
    background_tasks.add_task(container.dispatcher.dispatch, created.attempt_id)
    return GenerateResponse(task_id=created.task_id)
