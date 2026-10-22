import uuid

from fastapi import APIRouter

from app.api.deps import ContainerDep
from app.api.schemas import AttemptOut, CurrentLegOut, TaskOut
from app.domain.enums import ACTIVE_ATTEMPT_STATUSES

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(task_id: uuid.UUID, container: ContainerDep) -> TaskOut:
    view = await container.tasks.get(task_id)
    task = view.task
    attempts = [
        AttemptOut(
            id=attempt.id,
            provider=attempt.provider,
            priority=attempt.leg.priority,
            status=attempt.status,
            external_id=attempt.external_id,
            error_type=attempt.error_type,
            error_detail=attempt.error_detail,
            result_url=attempt.result_url,
            late_result=attempt.late_result,
            started_at=attempt.created_at,
            deadline_at=attempt.deadline_at,
            finished_at=attempt.finished_at,
        )
        for attempt in view.attempts
    ]
    current = next((a for a in reversed(attempts) if a.status in ACTIVE_ATTEMPT_STATUSES), None)
    current = current or (attempts[-1] if attempts else None)
    return TaskOut(
        id=task.id,
        user_id=task.user_id,
        model_slug=task.model_slug,
        status=task.status,
        price=task.price,
        result_url=task.result_url,
        error=task.error,
        created_at=task.created_at,
        finished_at=task.finished_at,
        current_leg=CurrentLegOut(
            attempt_id=current.id, provider=current.provider, priority=current.priority, status=current.status
        )
        if current
        else None,
        attempts=attempts,
    )
