from datetime import datetime
from pydantic import BaseModel


class SplatSceneRead(BaseModel):
    id: int
    slug: str
    title: str
    description: str | None = None
    image_url: str
    scene_url: str
    # vec3 camera spawn — passed straight through to the renderer's
    # `?eye=x,y,z&fwd=x,y,z` query params on the iframe URL.
    camera_eye: list[float]
    camera_fwd: list[float]
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
