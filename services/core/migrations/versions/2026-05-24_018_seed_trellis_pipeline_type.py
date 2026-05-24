"""seed trellis pipeline_type

Revision ID: 018
Revises: 017
Create Date: 2026-05-24

"""

from alembic import op


revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


TRELLIS_BASE_COST = 20


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO pipeline_types (name, base_cost)
        VALUES ('trellis', {TRELLIS_BASE_COST})
        ON CONFLICT (name) DO NOTHING
        """
    )


def downgrade() -> None:
    # Skip removal if any token_transactions reference this row (FK).
    op.execute(
        """
        DELETE FROM pipeline_types
        WHERE name = 'trellis'
          AND NOT EXISTS (
            SELECT 1 FROM token_transactions tt
            WHERE tt.pipeline_type_id = pipeline_types.id
          )
        """
    )
