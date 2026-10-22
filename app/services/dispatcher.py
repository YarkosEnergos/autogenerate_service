import logging
import uuid

from app.clients.providers import ProviderError, ProviderGateway
from app.services.tasks import TaskService

logger = logging.getLogger(__name__)


class Dispatcher:
    def __init__(self, tasks: TaskService, gateway: ProviderGateway) -> None:
        self._tasks = tasks
        self._gateway = gateway

    async def dispatch(self, attempt_id: uuid.UUID | None) -> None:
        try:
            await self._dispatch_chain(attempt_id)
        except Exception:
            logger.exception("dispatch of attempt %s crashed, watchdog will pick it up", attempt_id)

    async def _dispatch_chain(self, attempt_id: uuid.UUID | None) -> None:
        while attempt_id is not None:
            submission = await self._tasks.submission_for(attempt_id)
            if submission is None:
                return
            try:
                external_id = await self._gateway.submit(submission)
            except ProviderError as exc:
                logger.warning("attempt %s: %s rejected synchronously: %s", attempt_id, submission.provider, exc)
                attempt_id = await self._tasks.fail_on_submit(attempt_id, exc)
                continue
            await self._tasks.mark_sent(attempt_id, external_id)
            return
