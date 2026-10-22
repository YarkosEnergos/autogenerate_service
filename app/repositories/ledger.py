import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LedgerEntry
from app.domain.enums import LedgerReason


class LedgerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_once(
        self,
        *,
        user_id: int,
        amount: int,
        reason: LedgerReason,
        task_id: uuid.UUID | None = None,
        payment_id: str | None = None,
    ) -> bool:
        stmt = (
            insert(LedgerEntry)
            .values(user_id=user_id, amount=amount, reason=reason, task_id=task_id, payment_id=payment_id)
            .on_conflict_do_nothing()
            .returning(LedgerEntry.id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def recent(self, user_id: int, limit: int) -> list[LedgerEntry]:
        result = await self._session.execute(
            select(LedgerEntry).where(LedgerEntry.user_id == user_id).order_by(LedgerEntry.id.desc()).limit(limit)
        )
        return list(result.scalars())
