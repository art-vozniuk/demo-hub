"""create pipeline_payloads table

Revision ID: 005
Revises: 004
Create Date: 2026-05-07

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Single row per pipeline. Stores structured pipeline output (e.g. the
    # face_recognition pipeline's detected faces). The pipeline_name on
    # the parent `pipelines` row already encodes the JSON's shape, so no
    # additional payload_type column is needed.
    op.create_table(
        "pipeline_payloads",
        sa.Column("pipeline_id", UUID(as_uuid=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
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
        sa.PrimaryKeyConstraint("pipeline_id"),
        sa.ForeignKeyConstraint(
            ["pipeline_id"],
            ["pipelines.id"],
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("pipeline_payloads")
