"""seed sharp pipeline_type

Revision ID: 009
Revises: 008
Create Date: 2026-05-12

"""

from alembic import op


revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


# Same ballpark as generative_editing; tune from observed Modal costs.
SHARP_BASE_COST = 10


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO pipeline_types (name, base_cost)
        VALUES ('sharp', {SHARP_BASE_COST})
        ON CONFLICT (name) DO NOTHING
        """
    )


def downgrade() -> None:
    # Skip removal if any token_transactions reference this row (FK).
    op.execute(
        """
        DELETE FROM pipeline_types
        WHERE name = 'sharp'
          AND NOT EXISTS (
            SELECT 1 FROM token_transactions tt
            WHERE tt.pipeline_type_id = pipeline_types.id
          )
        """
    )
