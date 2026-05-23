import logging
import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import EditorScene
from .storage import (
    delete_keys,
    list_keys_under_prefix,
    manifest_asset_urls,
    url_to_key,
)

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


async def get_scene_by_id(db: AsyncSession, scene_id: UUID) -> EditorScene | None:
    # Owner-less lookup. Only used by the public default-scene endpoint —
    # callers MUST NOT expose this to user-supplied ids.
    result = await db.execute(select(EditorScene).where(EditorScene.id == scene_id))
    return result.scalar_one_or_none()


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
    # Diff asset URLs to find ones dropped this save; delete from storage.
    old_urls = manifest_asset_urls(scene.manifest or {})
    new_urls = manifest_asset_urls(manifest or {})
    dropped = [u for u in (old_urls - new_urls)]
    scene.name = name
    scene.manifest = manifest
    await db.flush()
    await db.commit()
    await db.refresh(scene)
    if dropped:
        keys = [k for k in (url_to_key(u) for u in dropped) if k]
        if keys:
            await delete_keys(keys)
    return scene


async def delete_scene(db: AsyncSession, scene: EditorScene) -> None:
    # Capture the scene_id before SQLAlchemy expires the row on delete.
    user_id = scene.user_id
    scene_id = scene.id
    await db.delete(scene)
    await db.commit()
    # Best-effort: list everything under the scene's asset prefix and drop it.
    prefix = f"editor-assets/{user_id}/{scene_id}"
    keys = await list_keys_under_prefix(prefix)
    if keys:
        await delete_keys(keys)
