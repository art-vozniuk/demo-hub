"""create generative_presets table + seed

Revision ID: 007
Revises: 006
Create Date: 2026-05-09

"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


# Public Supabase Storage URLs of preview images. The runtime pipeline
# never reads these — they are UI-only showcase assets. Replace the slug
# segment with the actual filename in the bucket.
SUPABASE_BASE = (
    "https://glabfxjyvsflllgldiwq.supabase.co/storage/v1/object/public/media/generative"
)


SEED_PRESETS = [
    {
        "slug": "neo-tokyo",
        "title": "Neo Tokyo",
        "description": (
            "Cyberpunk Tokyo at midnight — neon reflections on wet asphalt, "
            "katakana signage, anamorphic flares."
        ),
        "prompt": (
            "cinematic still of the subject standing in a rain-soaked Tokyo "
            "alley at night, towering neon signs in Japanese, holographic "
            "billboards, anamorphic lens flares, volumetric fog, shot on "
            "ARRI Alexa, 35mm, shallow depth of field, blade runner aesthetic"
        ),
        "preview_image_url": f"{SUPABASE_BASE}/previews/neo-tokyo.jpg",
        "sort_order": 10,
    },
    {
        "slug": "ps2-horror",
        "title": "PS2 Horror",
        "description": (
            "Low-poly survival horror — Silent Hill fog, VHS grain, "
            "PS2-era 480i texture work."
        ),
        "prompt": (
            "subject rendered as a PS2-era survival horror character, "
            "low-poly 3d, blocky polygons, blurred low-res textures, fog "
            "obscuring the background, dim CRT lighting, VHS scanlines, "
            "Silent Hill 2 aesthetic, dread atmosphere"
        ),
        "preview_image_url": f"{SUPABASE_BASE}/previews/ps2-horror.jpg",
        "sort_order": 20,
    },
    {
        "slug": "anime-opening",
        "title": "Anime Opening",
        "description": (
            "90s anime opening cel — vivid lineart, dramatic backlight, "
            "wind-blown hair frame."
        ),
        "prompt": (
            "subject as the protagonist of a 1990s anime opening sequence, "
            "hand-drawn cel animation, bold lineart, vivid limited palette, "
            "dramatic rim lighting, wind blowing hair, sakura petals "
            "drifting, 4:3 aspect framing, Studio Gainax aesthetic"
        ),
        "preview_image_url": f"{SUPABASE_BASE}/previews/anime-opening.jpg",
        "sort_order": 30,
    },
    {
        "slug": "dark-fantasy",
        "title": "Dark Fantasy",
        "description": (
            "Plate-armoured warrior — torchlit gothic stonework, dust "
            "motes, oil-painting palette."
        ),
        "prompt": (
            "subject as a battle-worn dark fantasy warrior in ornate plate "
            "armour, weathered cloak, standing in a torch-lit gothic "
            "cathedral, dust motes, deep chiaroscuro, oil-painting palette, "
            "Frank Frazetta aesthetic, cinematic"
        ),
        "preview_image_url": f"{SUPABASE_BASE}/previews/dark-fantasy.jpg",
        "sort_order": 40,
    },
    {
        "slug": "toy-packaging",
        "title": "Toy Packaging",
        "description": (
            "Action-figure blister pack — saturated cardboard, plastic "
            "bubble, retail-shelf product photography."
        ),
        "prompt": (
            "subject as an action figure sealed in retail blister-pack "
            "packaging, glossy printed cardboard backing in saturated "
            "primary colours, plastic bubble, accessories arranged beside "
            "the figure, studio product photography, sharp focus, 1990s "
            "toy aisle aesthetic"
        ),
        "preview_image_url": f"{SUPABASE_BASE}/previews/toy-packaging.jpg",
        "sort_order": 50,
    },
    {
        "slug": "retro-action",
        "title": "Retro Action Movie",
        "description": (
            "80s action hero on 35mm — magic-hour backlight, practical "
            "effects, Kodachrome grading."
        ),
        "prompt": (
            "subject as the lead of a 1980s action movie, practical "
            "explosion behind them, magic-hour backlight, 35mm film grain, "
            "Kodachrome colour grade, leather jacket, Stallone-era "
            "cinematography, anamorphic widescreen"
        ),
        "preview_image_url": f"{SUPABASE_BASE}/previews/retro-action.jpg",
        "sort_order": 60,
    },
]


def upgrade() -> None:
    op.create_table(
        "generative_presets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("preview_image_url", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_generative_presets_slug"),
    )
    op.create_index(
        op.f("ix_generative_presets_id"),
        "generative_presets",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_generative_presets_slug"),
        "generative_presets",
        ["slug"],
        unique=True,
    )

    table = sa.table(
        "generative_presets",
        sa.column("slug", sa.String),
        sa.column("title", sa.String),
        sa.column("description", sa.Text),
        sa.column("prompt", sa.Text),
        sa.column("preview_image_url", sa.String),
        sa.column("sort_order", sa.Integer),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    op.bulk_insert(
        table,
        [{**row, "created_at": now, "updated_at": now} for row in SEED_PRESETS],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_generative_presets_slug"), table_name="generative_presets")
    op.drop_index(op.f("ix_generative_presets_id"), table_name="generative_presets")
    op.drop_table("generative_presets")
