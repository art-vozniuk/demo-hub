from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, event


class TimeStampMixin:
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    @staticmethod
    def _updated_at(mapper, connection, target):
        target.updated_at = datetime.now(timezone.utc)

    @classmethod
    def __declare_last__(cls):
        event.listen(cls, "before_update", cls._updated_at)
