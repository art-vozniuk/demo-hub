import logging
import random
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import RecastTemplate

log = logging.getLogger(__name__)


async def get_all_templates(db: AsyncSession) -> list[RecastTemplate]:
    result = await db.execute(select(RecastTemplate))
    templates = list(result.scalars().all())
    random.shuffle(templates)
    return templates


async def get_template_by_id(
    db: AsyncSession, template_id: int
) -> RecastTemplate | None:
    result = await db.execute(
        select(RecastTemplate).where(RecastTemplate.id == template_id)
    )
    return result.scalar_one_or_none()
