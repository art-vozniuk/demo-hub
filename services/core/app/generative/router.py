import logging

from fastapi import APIRouter, HTTPException, status

from services.common.database import DbSession

from .schemas import GenerativePresetRead
from . import service

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/presets", response_model=list[GenerativePresetRead])
async def list_presets(db: DbSession):
    return await service.get_all_presets(db)


@router.get("/presets/{slug}", response_model=GenerativePresetRead)
async def get_preset(slug: str, db: DbSession):
    preset = await service.get_preset_by_slug(db, slug)
    if not preset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"preset with slug {slug!r} not found",
        )
    return preset
