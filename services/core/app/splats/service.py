import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import SplatScene

log = logging.getLogger(__name__)


async def get_all_scenes(db: AsyncSession) -> list[SplatScene]:
    # Hide soft-disabled scenes from the public catalog. Rows with
    # enabled=false stay in the table (assets in S3 too), they just
    # don't appear in the renderer grid.
    result = await db.execute(
        select(SplatScene)
        .where(SplatScene.enabled.is_(True))
        .order_by(SplatScene.sort_order.asc(), SplatScene.id.asc())
    )
    return list(result.scalars().all())
