from datetime import datetime
from pydantic import BaseModel


class GenerativePresetRead(BaseModel):
    """Public-facing preset card. The `prompt` is intentionally hidden:
    runtime resolves it server-side from the slug, so users never see it."""

    id: int
    slug: str
    title: str
    description: str | None = None
    preview_image_url: str
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GenerativePresetInternal(GenerativePresetRead):
    """Internal-only — includes the prompt template. Dispatch worker
    fetches this via /generative/internal/presets/{slug}."""

    prompt: str
