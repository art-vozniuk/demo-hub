"""add estimated_finish_at column to pipelines

Revision ID: 007
Revises: 006
Create Date: 2026-05-08

"""

from alembic import op
import sqlalchemy as sa


revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pipelines",
        sa.Column(
            "estimated_finish_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("pipelines", "estimated_finish_at")
