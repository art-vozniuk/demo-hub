"""create editor_scenes table

Revision ID: 016
Revises: 015
Create Date: 2026-05-23

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Per-user 3D editor scene. manifest is a JSON document storing the
    # full editor state (objects, transforms, asset URLs). RLS isn't
    # enforced at the DB layer — the API checks user_id ownership in the
    # service layer, matching the convention used by pipelines.
    op.create_table(
        "editor_scenes",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("manifest", JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_editor_scenes_user_id",
        "editor_scenes",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_editor_scenes_user_id", table_name="editor_scenes")
    op.drop_table("editor_scenes")
