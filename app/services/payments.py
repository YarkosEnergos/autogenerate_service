import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import LedgerEntry, User
from app.domain.errors import NotFoundError
from app.repositories.ledger import LedgerRepository
from app.repositories.users import UserRepository
from app.services.billing import Billing

logger = logging.getLogger(__name__)

SUCCEEDED = "succeeded"


@dataclass(frozen=True)
class PaymentEvent:
    payment_id: str
    user_id: int
    tokens: int
    status: str


@dataclass(frozen=True)
class BalanceView:
    user: User
    entries: list[LedgerEntry]


class PaymentService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], history_limit: int) -> None:
        self._session_factory = session_factory
        self._history_limit = history_limit

    async def process(self, event: PaymentEvent) -> bool:
        if event.status != SUCCEEDED:
            logger.info("payment %s ignored: status=%s", event.payment_id, event.status)
            return False
        async with self._session_factory() as session, session.begin():
            await UserRepository(session).ensure_exists(event.user_id)
            credited = await Billing(session).top_up(event.user_id, event.payment_id, event.tokens)
        logger.info("payment %s credited=%s", event.payment_id, credited)
        return credited

    async def balance(self, user_id: int) -> BalanceView:
        async with self._session_factory() as session:
            user = await UserRepository(session).get(user_id)
            if user is None:
                raise NotFoundError(f"user {user_id} not found")
            entries = await LedgerRepository(session).recent(user_id, self._history_limit)
        return BalanceView(user=user, entries=entries)
