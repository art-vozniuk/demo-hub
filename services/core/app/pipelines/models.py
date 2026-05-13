from sqlalchemy import Column, JSON, Text
from sqlalchemy.dialects.postgresql import UUID

from services.common.database import Base, TimeStampMixin


class Pipeline(Base, TimeStampMixin):
    __tablename__ = "pipelines"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True)
    trace_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    pipeline_name = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    input = Column(JSON, nullable=True)
    result = Column(JSON, nullable=True)
    message = Column(Text, nullable=True)
