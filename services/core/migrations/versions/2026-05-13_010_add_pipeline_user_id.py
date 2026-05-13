"""add user_id column to pipelines

Revision ID: 010
Revises: 009
Create Date: 2026-05-13

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pipelines",
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_pipelines_user_id_created_at",
        "pipelines",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_pipelines_user_id_created_at", table_name="pipelines")
    op.drop_column("pipelines", "user_id")
