import logging
from fastapi import APIRouter, HTTPException, status

from services.common.database import DbSession

from .schemas import RecastTemplateRead
from . import service

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/templates", response_model=list[RecastTemplateRead])
async def get_templates(db: DbSession):
    templates = await service.get_all_templates(db)
    return templates


@router.get("/templates/{template_id}", response_model=RecastTemplateRead)
async def get_template(template_id: int, db: DbSession):
    template = await service.get_template_by_id(db, template_id)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"template with id {template_id} not found",
        )
    return template
