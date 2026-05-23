import logging
import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import EditorScene

log = logging.getLogger(__name__)


async def create_scene(
    db: AsyncSession,
    user_id: UUID,
    name: str,
    manifest: dict[str, Any],
) -> EditorScene:
    scene = EditorScene(
        id=uuid.uuid4(),
        user_id=user_id,
        name=name,
        manifest=manifest,
    )
    db.add(scene)
    await db.flush()
    await db.commit()
    await db.refresh(scene)
    return scene


async def list_scenes_for_user(
    db: AsyncSession,
    user_id: UUID,
) -> list[EditorScene]:
    result = await db.execute(
        select(EditorScene)
        .where(EditorScene.user_id == user_id)
        .order_by(EditorScene.updated_at.desc())
    )
    return list(result.scalars().all())


async def get_scene_for_user(
    db: AsyncSession,
    user_id: UUID,
    scene_id: UUID,
) -> EditorScene | None:
    # user_id is part of the WHERE so a 404 is returned for both
    # "doesn't exist" and "not yours" — keeps the API from leaking
    # scene-id existence to non-owners.
    result = await db.execute(
        select(EditorScene)
        .where(EditorScene.id == scene_id)
        .where(EditorScene.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def update_scene(
    db: AsyncSession,
    scene: EditorScene,
    name: str,
    manifest: dict[str, Any],
) -> EditorScene:
    scene.name = name
    scene.manifest = manifest
    await db.flush()
    await db.commit()
    await db.refresh(scene)
    return scene


async def delete_scene(db: AsyncSession, scene: EditorScene) -> None:
    await db.delete(scene)
    await db.commit()
