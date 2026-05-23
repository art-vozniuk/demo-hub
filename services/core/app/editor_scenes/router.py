import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from services.common.auth.models import User
from services.common.database import DbSession

from . import service
from .schemas import (
    EditorSceneCreate,
    EditorSceneListItem,
    EditorSceneListResponse,
    EditorSceneRead,
    EditorSceneUpdate,
)

log = logging.getLogger(__name__)

router = APIRouter()

# Scene shown to anonymous visitors on /editor. Read-only via the
# /scenes/default route below. Hardcoded ID is fine while we have one
# curated demo scene.
DEFAULT_SCENE_ID = UUID("9a84f51e-54bf-4201-a094-56dd9fb41af3")


def _get_user_dep():
    # Lazy import to avoid circular-import friction with tests.
    from ..dependencies import get_current_user

    return get_current_user


@router.post("/scenes", response_model=EditorSceneRead, status_code=status.HTTP_201_CREATED)
async def create_scene(
    payload: EditorSceneCreate,
    db: DbSession,
    user: User = Depends(_get_user_dep()),
) -> EditorSceneRead:
    user_uuid = UUID(user.id)
    scene = await service.create_scene(
        db, user_id=user_uuid, name=payload.name, manifest=payload.manifest
    )
    return EditorSceneRead.model_validate(scene)


@router.get("/scenes", response_model=EditorSceneListResponse)
async def list_scenes(
    db: DbSession,
    user: User = Depends(_get_user_dep()),
) -> EditorSceneListResponse:
    user_uuid = UUID(user.id)
    scenes = await service.list_scenes_for_user(db, user_uuid)
    return EditorSceneListResponse(
        scenes=[EditorSceneListItem.model_validate(s) for s in scenes]
    )


@router.get("/scenes/default", response_model=EditorSceneRead)
async def get_default_scene(db: DbSession) -> EditorSceneRead:
    # Public; no auth dependency. Reads exactly DEFAULT_SCENE_ID.
    scene = await service.get_scene_by_id(db, DEFAULT_SCENE_ID)
    if scene is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Default scene not found"
        )
    return EditorSceneRead.model_validate(scene)


@router.get("/scenes/{scene_id}", response_model=EditorSceneRead)
async def get_scene(
    scene_id: UUID,
    db: DbSession,
    user: User = Depends(_get_user_dep()),
) -> EditorSceneRead:
    user_uuid = UUID(user.id)
    scene = await service.get_scene_for_user(db, user_uuid, scene_id)
    if scene is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene {scene_id} not found",
        )
    return EditorSceneRead.model_validate(scene)


@router.put("/scenes/{scene_id}", response_model=EditorSceneRead)
async def update_scene(
    scene_id: UUID,
    payload: EditorSceneUpdate,
    db: DbSession,
    user: User = Depends(_get_user_dep()),
) -> EditorSceneRead:
    user_uuid = UUID(user.id)
    scene = await service.get_scene_for_user(db, user_uuid, scene_id)
    if scene is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene {scene_id} not found",
        )
    scene = await service.update_scene(
        db, scene, name=payload.name, manifest=payload.manifest
    )
    return EditorSceneRead.model_validate(scene)


@router.delete("/scenes/{scene_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scene(
    scene_id: UUID,
    db: DbSession,
    user: User = Depends(_get_user_dep()),
) -> None:
    user_uuid = UUID(user.id)
    scene = await service.get_scene_for_user(db, user_uuid, scene_id)
    if scene is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene {scene_id} not found",
        )
    await service.delete_scene(db, scene)
