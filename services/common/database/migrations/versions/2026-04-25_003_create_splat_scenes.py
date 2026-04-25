"""create splat_scenes table + seed initial 3 scenes

Revision ID: 003
Revises: 002
Create Date: 2026-04-25

"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


# Public Supabase Storage URLs of the splat scenes + thumbnails. Files
# were uploaded to media/splats/{scenes,images}/ during the same change
# that introduced this migration; URLs are stable for the bucket's
# lifetime so embedding them as seed data is safe.
SUPABASE_BASE = (
    "https://glabfxjyvsflllgldiwq.supabase.co/storage/v1/object/public/media/splats"
)


SEED_SCENES = [
    {
        "slug": "train",
        "title": "Train",
        "description": (
            "Trainset locomotive — the antimatter15 reference scene. ~1M "
            "splats, ~31 MB."
        ),
        "image_url": f"{SUPABASE_BASE}/images/train.jpg",
        "scene_url": f"{SUPABASE_BASE}/scenes/train.splat",
        # Original framing the renderer was tuned for (engine-side default).
        "camera_eye": [-4.6, 0.7, 4.3],
        "camera_fwd": [0.49, -0.14, -0.86],
        "sort_order": 10,
    },
    {
        "slug": "nike",
        "title": "Nike Vaporfly",
        "description": "Single-shoe capture, ~270k splats, ~8 MB.",
        "image_url": f"{SUPABASE_BASE}/images/nike.jpg",
        "scene_url": f"{SUPABASE_BASE}/scenes/nike.splat",
        "camera_eye": [2.0, -1.5, 2.0],
        "camera_fwd": [-0.5, -0.3, -1.0],
        "sort_order": 20,
    },
    {
        "slug": "plush",
        "title": "Plush Reindeer",
        "description": "Holiday plush on a wooden sleigh, ~280k splats, ~9 MB.",
        "image_url": f"{SUPABASE_BASE}/images/plush.jpg",
        "scene_url": f"{SUPABASE_BASE}/scenes/plush.splat",
        "camera_eye": [0.0, -0.5, 2.0],
        "camera_fwd": [0.0, -0.4, -1.0],
        "sort_order": 30,
    },
]


def upgrade() -> None:
    op.create_table(
        "splat_scenes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image_url", sa.String(), nullable=False),
        sa.Column("scene_url", sa.String(), nullable=False),
        # vec3 stored as ARRAY[3] FLOAT — easier to read in SQL than JSONB
        # while still letting us pull the whole tuple in one column.
        sa.Column("camera_eye", ARRAY(sa.Float(), dimensions=1), nullable=False),
        sa.Column("camera_fwd", ARRAY(sa.Float(), dimensions=1), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_splat_scenes_slug"),
    )
    op.create_index(op.f("ix_splat_scenes_id"), "splat_scenes", ["id"], unique=False)
    op.create_index(op.f("ix_splat_scenes_slug"), "splat_scenes", ["slug"], unique=True)

    # Seed 3 starter scenes. Bulk insert via op.bulk_insert reflects the
    # full table schema, so created_at / updated_at need explicit values
    # (TimeStampMixin's default doesn't fire during raw migrations).
    splat_scenes = sa.table(
        "splat_scenes",
        sa.column("slug", sa.String),
        sa.column("title", sa.String),
        sa.column("description", sa.Text),
        sa.column("image_url", sa.String),
        sa.column("scene_url", sa.String),
        sa.column("camera_eye", ARRAY(sa.Float(), dimensions=1)),
        sa.column("camera_fwd", ARRAY(sa.Float(), dimensions=1)),
        sa.column("sort_order", sa.Integer),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    # Python datetime rather than sa.func.now() — the latter doesn't bind
    # cleanly through asyncpg's executemany path (it expects a real
    # datetime per row, not a SQL function expression).
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    op.bulk_insert(
        splat_scenes,
        [{**row, "created_at": now, "updated_at": now} for row in SEED_SCENES],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_splat_scenes_slug"), table_name="splat_scenes")
    op.drop_index(op.f("ix_splat_scenes_id"), table_name="splat_scenes")
    op.drop_table("splat_scenes")
