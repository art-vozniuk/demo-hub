from sqlalchemy import Column, ForeignKey, JSON, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from services.common.database import Base, TimeStampMixin


class Pipeline(Base, TimeStampMixin):
    __tablename__ = "pipelines"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True)
    trace_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    pipeline_name = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    result_url = Column(Text, nullable=True)
    message = Column(Text, nullable=True)

    payload = relationship(
        "PipelinePayload",
        uselist=False,
        back_populates="pipeline",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PipelinePayload(Base, TimeStampMixin):
    # Single-row-per-pipeline JSON output. Pipeline name on the parent row
    # implicitly defines the JSON shape (e.g. face_recognition stores
    # {image_width, image_height, faces:[{id, bbox, det_score}]}). When we
    # add new pipelines whose output isn't a final image artifact, they
    # write their structured output here too.
    __tablename__ = "pipeline_payloads"

    pipeline_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pipelines.id", ondelete="CASCADE"),
        primary_key=True,
    )
    payload = Column(JSON, nullable=False)

    pipeline = relationship("Pipeline", back_populates="payload")
