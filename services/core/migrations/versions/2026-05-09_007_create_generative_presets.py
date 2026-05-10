"""create generative_presets table

Revision ID: 007
Revises: 006
Create Date: 2026-05-09

"""

from alembic import op
import sqlalchemy as sa


revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


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


def downgrade() -> None:
    op.drop_index(op.f("ix_generative_presets_slug"), table_name="generative_presets")
    op.drop_index(op.f("ix_generative_presets_id"), table_name="generative_presets")
    op.drop_table("generative_presets")
