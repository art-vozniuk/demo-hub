from sqlalchemy import JSON, Column, Integer, String, Text

from services.common.database import Base, TimeStampMixin


class SplatScene(Base, TimeStampMixin):
    """
    A Gaussian Splatting scene that the renderer can stream from S3.

    `scene_url` and `image_url` point at Supabase Storage objects under
    `media/splats/scenes/` and `media/splats/images/` respectively. Camera
    spawn is stored as ARRAY[3] FLOAT (a vec3) so the frontend can pass
    `?eye=x,y,z&fwd=x,y,z` to the WASM iframe — adding a new scene with
    a different framing requires no renderer rebuild.
    """

    __tablename__ = "splat_scenes"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String, nullable=False, unique=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    image_url = Column(String, nullable=False)
    scene_url = Column(String, nullable=False)
    # vec3 stored as JSON array — generic SQLAlchemy JSON type so the
    # tests' SQLite engine can round-trip it (PostgreSQL dialect compiles
    # this to native JSON; SQLite stores it as TEXT with automatic
    # serialisation).
    camera_eye = Column(JSON, nullable=False)
    camera_fwd = Column(JSON, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
