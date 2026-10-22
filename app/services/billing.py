import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import LedgerReason
from app.repositories.ledger import LedgerRepository
from app.repositories.users import UserRepository


class Billing:
    def __init__(self, session: AsyncSession) -> None:
        self._users = UserRepository(session)
        self._ledger = LedgerRepository(session)

    async def top_up(self, user_id: int, payment_id: str, tokens: int) -> bool:
        return await self._post(user_id, tokens, LedgerReason.TOPUP, payment_id=payment_id)

    async def charge(self, user_id: int, task_id: uuid.UUID, tokens: int) -> bool:
        return await self._post(user_id, -tokens, LedgerReason.CHARGE, task_id=task_id)

    async def refund(self, user_id: int, task_id: uuid.UUID, tokens: int) -> bool:
        return await self._post(user_id, tokens, LedgerReason.REFUND, task_id=task_id)

    async def _post(
        self,
        user_id: int,
        amount: int,
        reason: LedgerReason,
        *,
        task_id: uuid.UUID | None = None,
        payment_id: str | None = None,
    ) -> bool:
        inserted = await self._ledger.insert_once(
            user_id=user_id, amount=amount, reason=reason, task_id=task_id, payment_id=payment_id
        )
        if inserted:
            await self._users.add_to_balance(user_id, amount)
        return inserted
