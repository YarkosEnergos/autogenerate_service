import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.providers import ProviderError, Submission
from app.core.config import Settings
from app.db.models import Attempt, Task
from app.domain.enums import ACTIVE_ATTEMPT_STATUSES, AttemptStatus, ErrorType, LateResult, TaskStatus
from app.domain.errors import (
    InsufficientTokensError,
    NoSuitableLegError,
    NotFoundError,
    TooManyActiveTasksError,
)
from app.domain.routing import next_leg, suitable_legs
from app.repositories.catalog import CatalogRepository
from app.repositories.tasks import TaskRepository
from app.repositories.users import UserRepository
from app.services.billing import Billing

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GenerateCommand:
    user_id: int
    model_slug: str
    prompt: str
    ref_images: list[str]


@dataclass(frozen=True)
class CreatedTask:
    task_id: uuid.UUID
    attempt_id: uuid.UUID


@dataclass(frozen=True)
class ProviderResult:
    client_ref: uuid.UUID
    external_id: str | None
    completed: bool
    result_url: str | None = None
    error_type: ErrorType | None = None
    detail: str | None = None


@dataclass(frozen=True)
class TaskView:
    task: Task
    attempts: list[Attempt]


class TaskService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._session_factory = session_factory
        self._settings = settings

    async def create(self, command: GenerateCommand) -> CreatedTask:
        async with self._session_factory() as session, session.begin():
            model = await CatalogRepository(session).get_model(command.model_slug)
            if model is None:
                raise NotFoundError(f"model {command.model_slug} not found")
            legs = suitable_legs(model.legs, len(command.ref_images))
            if not legs:
                raise NoSuitableLegError(f"no leg of {model.slug} accepts {len(command.ref_images)} reference images")

            user = await UserRepository(session).get_for_update(command.user_id)
            if user is None:
                raise NotFoundError(f"user {command.user_id} not found")
            if user.balance < model.price:
                raise InsufficientTokensError(f"balance {user.balance} is less than price {model.price}")
            tasks = TaskRepository(session)
            if await tasks.count_processing(user.id) >= self._settings.max_active_tasks:
                raise TooManyActiveTasksError(f"user already has {self._settings.max_active_tasks} active tasks")

            task = Task(
                user_id=user.id,
                model_slug=model.slug,
                prompt=command.prompt,
                ref_images=command.ref_images,
                price=model.price,
                status=TaskStatus.PROCESSING,
            )
            await tasks.add_task(task)
            await Billing(session).charge(user.id, task.id, model.price)
            attempt = await tasks.add_attempt(task, legs[0], self._settings.provider_timeout)
            return CreatedTask(task_id=task.id, attempt_id=attempt.id)

    async def get(self, task_id: uuid.UUID) -> TaskView:
        async with self._session_factory() as session:
            tasks = TaskRepository(session)
            task = await tasks.get_task(task_id)
            if task is None:
                raise NotFoundError(f"task {task_id} not found")
            return TaskView(task=task, attempts=await tasks.attempts_of(task_id))

    async def submission_for(self, attempt_id: uuid.UUID) -> Submission | None:
        async with self._session_factory() as session:
            tasks = TaskRepository(session)
            attempt = await tasks.get_attempt(attempt_id)
            if attempt is None or attempt.status != AttemptStatus.PENDING:
                return None
            task = await tasks.get_task(attempt.task_id)
            if task is None or task.status != TaskStatus.PROCESSING:
                return None
            return Submission(
                provider=attempt.provider,
                client_ref=attempt.id,
                prompt=task.prompt,
                ref_images=list(task.ref_images),
            )

    async def mark_sent(self, attempt_id: uuid.UUID, external_id: str) -> None:
        async with self._session_factory() as session, session.begin():
            await TaskRepository(session).mark_sent(attempt_id, external_id)

    async def fail_on_submit(self, attempt_id: uuid.UUID, error: ProviderError) -> uuid.UUID | None:
        async with self._session_factory() as session, session.begin():
            locked = await self._lock(session, attempt_id)
            if locked is None:
                return None
            task, attempt = locked
            if task.status != TaskStatus.PROCESSING or attempt.status not in ACTIVE_ATTEMPT_STATUSES:
                return None
            return await self._fail_attempt(
                session, task, attempt, AttemptStatus.FAILED, error.error_type, error.detail
            )

    async def apply_result(self, provider: str, result: ProviderResult) -> uuid.UUID | None:
        async with self._session_factory() as session, session.begin():
            locked = await self._lock(session, result.client_ref, provider)
            if locked is None:
                raise NotFoundError(f"attempt {result.client_ref} of provider {provider} not found")
            task, attempt = locked
            if result.external_id and attempt.external_id is None:
                attempt.external_id = result.external_id
            if result.completed:
                await self._apply_completed(session, task, attempt, result.result_url or "")
                return None
            if task.status != TaskStatus.PROCESSING or attempt.status not in ACTIVE_ATTEMPT_STATUSES:
                logger.info("task %s: duplicate or late failure from %s ignored", task.id, provider)
                return None
            return await self._fail_attempt(
                session, task, attempt, AttemptStatus.FAILED, result.error_type or ErrorType.TECHNICAL, result.detail
            )

    async def expire_next(self) -> tuple[bool, uuid.UUID | None]:
        async with self._session_factory() as session, session.begin():
            tasks = TaskRepository(session)
            claimed = await tasks.claim_expired()
            if claimed is None:
                return False, None
            task_id, attempt_id = claimed
            task = await tasks.get_task_for_update(task_id)
            attempt = await tasks.get_attempt(attempt_id)
            if (
                task is None
                or attempt is None
                or task.status != TaskStatus.PROCESSING
                or attempt.status not in ACTIVE_ATTEMPT_STATUSES
                or not await tasks.is_expired(attempt_id)
            ):
                return True, None
            detail = f"no result within {self._settings.provider_timeout:g}s"
            next_attempt_id = await self._fail_attempt(
                session, task, attempt, AttemptStatus.TIMED_OUT, ErrorType.TIMEOUT, detail
            )
            return True, next_attempt_id

    async def _apply_completed(self, session: AsyncSession, task: Task, attempt: Attempt, result_url: str) -> None:
        if attempt.status == AttemptStatus.COMPLETED:
            return
        is_active = attempt.status in ACTIVE_ATTEMPT_STATUSES
        attempt.result_url = result_url
        if task.status != TaskStatus.PROCESSING:
            attempt.late_result = LateResult.IGNORED
            logger.info("task %s is already %s, late result of %s ignored", task.id, task.status, attempt.provider)
            return
        if not is_active:
            attempt.late_result = LateResult.ACCEPTED
        else:
            attempt.finished_at = func.now()
        attempt.status = AttemptStatus.COMPLETED
        await session.flush()
        await TaskRepository(session).cancel_active_attempts(task.id)
        task.status = TaskStatus.COMPLETED
        task.result_url = result_url
        task.finished_at = func.now()
        logger.info("task %s completed by %s (late=%s)", task.id, attempt.provider, not is_active)

    async def _lock(
        self, session: AsyncSession, attempt_id: uuid.UUID, provider: str | None = None
    ) -> tuple[Task, Attempt] | None:
        tasks = TaskRepository(session)
        task_id = await tasks.task_id_of_attempt(attempt_id, provider)
        if task_id is None:
            return None
        task = await tasks.get_task_for_update(task_id)
        attempt = await tasks.get_attempt(attempt_id)
        if task is None or attempt is None:
            return None
        return task, attempt

    async def _fail_attempt(
        self,
        session: AsyncSession,
        task: Task,
        attempt: Attempt,
        status: AttemptStatus,
        error_type: ErrorType,
        detail: str | None,
    ) -> uuid.UUID | None:
        attempt.status = status
        attempt.error_type = error_type
        attempt.error_detail = detail
        attempt.finished_at = func.now()
        await session.flush()

        legs = await CatalogRepository(session).legs_of(task.model_slug)
        leg = next_leg(legs, len(task.ref_images), attempt.leg.priority, error_type)
        if leg is None:
            await self._fail_task(session, task, f"{attempt.provider}: {error_type}")
            return None
        new_attempt = await TaskRepository(session).add_attempt(task, leg, self._settings.provider_timeout)
        logger.info("task %s: %s failed (%s), next leg %s", task.id, attempt.provider, error_type, leg.provider)
        return new_attempt.id

    async def _fail_task(self, session: AsyncSession, task: Task, reason: str) -> None:
        task.status = TaskStatus.FAILED
        task.error = reason
        task.finished_at = func.now()
        refunded = await Billing(session).refund(task.user_id, task.id, task.price)
        logger.info("task %s failed (%s), refunded=%s", task.id, reason, refunded)
