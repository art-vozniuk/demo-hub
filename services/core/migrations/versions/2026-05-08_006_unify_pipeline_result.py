"""unify pipeline result column

Revision ID: 006
Revises: 005
Create Date: 2026-05-08

"""

from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("pipeline_payloads")
    op.drop_column("pipelines", "result_url")
    op.add_column("pipelines", sa.Column("result", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("pipelines", "result")
    op.add_column("pipelines", sa.Column("result_url", sa.Text(), nullable=True))
    op.create_table(
        "pipeline_payloads",
        sa.Column(
            "pipeline_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False
        ),
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
