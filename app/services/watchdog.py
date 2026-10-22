import asyncio
import logging

from app.services.dispatcher import Dispatcher
from app.services.tasks import TaskService

logger = logging.getLogger(__name__)


class Watchdog:
    def __init__(self, tasks: TaskService, dispatcher: Dispatcher, interval: float, batch_limit: int = 100) -> None:
        self._tasks = tasks
        self._dispatcher = dispatcher
        self._interval = interval
        self._batch_limit = batch_limit

    async def run_once(self) -> int:
        processed = 0
        for _ in range(self._batch_limit):
            claimed, next_attempt_id = await self._tasks.expire_next()
            if not claimed:
                break
            processed += 1
            if next_attempt_id is not None:
                await self._dispatcher.dispatch(next_attempt_id)
        return processed

    async def run_forever(self) -> None:
        while True:
            try:
                processed = await self.run_once()
                if processed:
                    logger.info("watchdog expired %d attempts", processed)
            except Exception:
                logger.exception("watchdog iteration failed")
            await asyncio.sleep(self._interval)
