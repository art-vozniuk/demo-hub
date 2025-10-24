from sqlalchemy import Column, Text
from sqlalchemy.dialects.postgresql import UUID

from services.common.database import Base, TimeStampMixin


class Pipeline(Base, TimeStampMixin):
    __tablename__ = "pipelines"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True)
    trace_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    pipeline_name = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    result_url = Column(Text, nullable=True)
    message = Column(Text, nullable=True)
