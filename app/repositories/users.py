from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: int) -> User | None:
        return await self._session.get(User, user_id)

    async def get_for_update(self, user_id: int) -> User | None:
        result = await self._session.execute(select(User).where(User.id == user_id).with_for_update())
        return result.scalar_one_or_none()

    async def ensure_exists(self, user_id: int) -> None:
        await self._session.execute(insert(User).values(id=user_id).on_conflict_do_nothing())

    async def add_to_balance(self, user_id: int, amount: int) -> None:
        await self._session.execute(
            update(User)
            .where(User.id == user_id)
            .values(balance=User.balance + amount)
            .execution_options(synchronize_session=False)
        )
