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


class EditorSceneListItem(BaseModel):
    # Manifest omitted from the list view — it's potentially large.
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EditorSceneListResponse(BaseModel):
    scenes: list[EditorSceneListItem]
