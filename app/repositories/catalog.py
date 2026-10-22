from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import GenerationModel, Leg


class CatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_model(self, slug: str) -> GenerationModel | None:
        result = await self._session.execute(
            select(GenerationModel).where(GenerationModel.slug == slug).options(selectinload(GenerationModel.legs))
        )
        return result.scalar_one_or_none()

    async def legs_of(self, slug: str) -> list[Leg]:
        result = await self._session.execute(select(Leg).where(Leg.model_slug == slug).order_by(Leg.priority))
        return list(result.scalars())
