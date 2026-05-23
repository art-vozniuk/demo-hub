import uuid

from sqlalchemy import Column, JSON, Text
from sqlalchemy.dialects.postgresql import UUID

from services.common.database import Base, TimeStampMixin


class EditorScene(Base, TimeStampMixin):
    """Per-user 3D editor scene. `manifest` holds the JSON document
    describing the editor state (objects + asset URLs + transforms).
    Ownership is enforced at the service layer via user_id."""

    __tablename__ = "editor_scenes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(Text, nullable=False)
    # JSON (generic) round-trips on both Postgres (JSONB column from the
    # migration) and the SQLite engine the test suite spins up.
    manifest = Column(JSON, nullable=False)
