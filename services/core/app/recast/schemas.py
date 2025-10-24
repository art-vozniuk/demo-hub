from datetime import datetime
from pydantic import BaseModel


class RecastTemplateBase(BaseModel):
    name: str | None = None
    description: str | None = None
    url: str


class RecastTemplateRead(RecastTemplateBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
