"""add visible_in_user_history to pipeline_types

Revision ID: 011
Revises: 010
Create Date: 2026-05-13

"""

from alembic import op
import sqlalchemy as sa

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pipeline_types",
        sa.Column(
            "visible_in_user_history",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    # Face recognition is a building block of other flows, not a top-level
    # pipeline a user would think of as "mine" — hide it from history.
    op.execute(
        "UPDATE pipeline_types SET visible_in_user_history = FALSE "
        "WHERE name = 'face_recognition'"
    )


def downgrade() -> None:
    op.drop_column("pipeline_types", "visible_in_user_history")
