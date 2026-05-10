"""Pipeline-specific input resolution at enqueue time.

Some pipelines need server-side data baked into the queued payload so
workers stay independent of core's HTTP API. Resolution happens once,
synchronously with the queue request, and the augmented dict is what
ends up on RabbitMQ.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from services.core.app.generative import service as generative_service


async def resolve_pipeline_input(
    db: AsyncSession,
    pipeline_name: str,
    input: dict,
) -> dict:
    if pipeline_name == "generative_editing":
        slug = input.get("preset_slug")
        if not slug:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="generative_editing requires preset_slug",
            )
        preset = await generative_service.get_preset_by_slug(db, slug)
        if preset is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"preset {slug!r} not found",
            )
        return {**input, "prompt": preset.prompt}

    return input
