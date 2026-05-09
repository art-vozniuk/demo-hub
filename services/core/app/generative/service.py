import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import GenerativePreset

log = logging.getLogger(__name__)


async def get_all_presets(db: AsyncSession) -> list[GenerativePreset]:
    result = await db.execute(
        select(GenerativePreset).order_by(
            GenerativePreset.sort_order, GenerativePreset.id
        )
    )
    return list(result.scalars().all())


async def get_preset_by_slug(db: AsyncSession, slug: str) -> GenerativePreset | None:
    result = await db.execute(
        select(GenerativePreset).where(GenerativePreset.slug == slug)
    )
    return result.scalar_one_or_none()
