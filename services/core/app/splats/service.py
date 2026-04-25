import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import SplatScene

log = logging.getLogger(__name__)


async def get_all_scenes(db: AsyncSession) -> list[SplatScene]:
    result = await db.execute(
        select(SplatScene).order_by(SplatScene.sort_order.asc(), SplatScene.id.asc())
    )
    return list(result.scalars().all())
