from sqlalchemy import Column, Integer, String

from services.common.database import Base, TimeStampMixin


class RecastTemplate(Base, TimeStampMixin):
    __tablename__ = "recast_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=True)
    description = Column(String, nullable=True)
    url = Column(String, nullable=False)
