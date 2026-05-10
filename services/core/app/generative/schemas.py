from datetime import datetime
from pydantic import BaseModel


class GenerativePresetRead(BaseModel):
    """Public-facing preset card. The `prompt` is intentionally hidden:
    core resolves it from the slug at pipeline enqueue time and bakes it
    into the worker's payload, so users never see it."""

    id: int
    slug: str
    title: str
    description: str | None = None
    preview_image_url: str
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
