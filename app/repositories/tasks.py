import uuid
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Attempt, Leg, Task
from app.domain.enums import ACTIVE_ATTEMPT_STATUSES, AttemptStatus, TaskStatus


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_task(self, task: Task) -> None:
        self._session.add(task)
        await self._session.flush()

    async def get_task(self, task_id: uuid.UUID) -> Task | None:
        return await self._session.get(Task, task_id)

    async def get_task_for_update(self, task_id: uuid.UUID) -> Task | None:
        result = await self._session.execute(
            select(Task).where(Task.id == task_id).with_for_update().execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def count_processing(self, user_id: int) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(Task).where(Task.user_id == user_id, Task.status == TaskStatus.PROCESSING)
        )
        return result.scalar_one()

    async def add_attempt(self, task: Task, leg: Leg, ttl_seconds: float) -> Attempt:
        attempt = Attempt(
            task_id=task.id,
            leg_id=leg.id,
            provider=leg.provider,
            status=AttemptStatus.PENDING,
            deadline_at=func.now() + timedelta(seconds=ttl_seconds),
        )
        self._session.add(attempt)
        await self._session.flush()
        return attempt

    async def get_attempt(self, attempt_id: uuid.UUID) -> Attempt | None:
        result = await self._session.execute(
            select(Attempt)
            .where(Attempt.id == attempt_id)
            .options(selectinload(Attempt.leg))
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def attempts_of(self, task_id: uuid.UUID) -> list[Attempt]:
        result = await self._session.execute(
            select(Attempt)
            .where(Attempt.task_id == task_id)
            .options(selectinload(Attempt.leg))
            .order_by(Attempt.created_at, Attempt.id)
        )
        return list(result.scalars())

    async def task_id_of_attempt(self, attempt_id: uuid.UUID, provider: str | None = None) -> uuid.UUID | None:
        stmt = select(Attempt.task_id).where(Attempt.id == attempt_id)
        if provider is not None:
            stmt = stmt.where(Attempt.provider == provider)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def mark_sent(self, attempt_id: uuid.UUID, external_id: str) -> None:
        await self._session.execute(
            update(Attempt)
            .where(Attempt.id == attempt_id, Attempt.status == AttemptStatus.PENDING)
            .values(status=AttemptStatus.SENT, external_id=external_id)
            .execution_options(synchronize_session=False)
        )

    async def cancel_active_attempts(self, task_id: uuid.UUID) -> None:
        await self._session.execute(
            update(Attempt)
            .where(Attempt.task_id == task_id, Attempt.status.in_(ACTIVE_ATTEMPT_STATUSES))
            .values(status=AttemptStatus.CANCELLED, finished_at=func.now())
            .execution_options(synchronize_session=False)
        )

    async def claim_expired(self) -> tuple[uuid.UUID, uuid.UUID] | None:
        result = await self._session.execute(
            select(Task.id, Attempt.id)
            .join(Attempt, Attempt.task_id == Task.id)
            .where(
                Task.status == TaskStatus.PROCESSING,
                Attempt.status.in_(ACTIVE_ATTEMPT_STATUSES),
                Attempt.deadline_at <= func.now(),
            )
            .order_by(Attempt.deadline_at)
            .limit(1)
            .with_for_update(of=Task, skip_locked=True)
        )
        row = result.first()
        return (row[0], row[1]) if row else None

    async def is_expired(self, attempt_id: uuid.UUID) -> bool:
        result = await self._session.execute(select(Attempt.deadline_at <= func.now()).where(Attempt.id == attempt_id))
        return bool(result.scalar_one())
