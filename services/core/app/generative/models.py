from sqlalchemy import Column, Integer, String, Text

from services.common.database import Base, TimeStampMixin


class GenerativePreset(Base, TimeStampMixin):
    __tablename__ = "generative_presets"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String, nullable=False, unique=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    prompt = Column(Text, nullable=False)
    preview_image_url = Column(String, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
