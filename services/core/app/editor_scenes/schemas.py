from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class EditorSceneCreate(BaseModel):
    name: str
    manifest: dict[str, Any]


class EditorSceneUpdate(BaseModel):
    name: str
    manifest: dict[str, Any]


class EditorSceneRead(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    manifest: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DefaultSceneRead(BaseModel):
    # Public, anonymous-visitor view of the curated default scene. Exposes
    # only what the renderer needs to display it — deliberately omits id and
    # user_id so the shared template's identity never leaks to clients.
    name: str
    manifest: dict[str, Any]

    model_config = {"from_attributes": True}


class EditorSceneListItem(BaseModel):
    # Manifest omitted from the list view — it's potentially large.
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EditorSceneListResponse(BaseModel):
    scenes: list[EditorSceneListItem]
