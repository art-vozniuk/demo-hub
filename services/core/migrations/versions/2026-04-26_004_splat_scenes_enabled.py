"""add enabled flag to splat_scenes

Revision ID: 004
Revises: 003
Create Date: 2026-04-26

"""

from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New rows default to enabled. Existing rows are bulk-set to true via
    # the server_default at column-add time — that's the only moment
    # Postgres rewrites the table to fill the new column, and we want
    # the existing four scenes to stay visible without a follow-up
    # UPDATE.
    op.add_column(
        "splat_scenes",
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("splat_scenes", "enabled")
