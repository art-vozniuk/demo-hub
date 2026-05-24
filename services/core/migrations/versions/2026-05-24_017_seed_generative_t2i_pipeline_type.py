"""seed generative_t2i pipeline_type

Revision ID: 017
Revises: 016
Create Date: 2026-05-24

"""

from alembic import op


revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


# FLUX.1 [schnell] in 4 steps is roughly as cheap to run as klein 4B's
# 4-step setup; same base cost as generative_editing_custom for parity.
GENERATIVE_T2I_BASE_COST = 10


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO pipeline_types (name, base_cost)
        VALUES ('generative_t2i', {GENERATIVE_T2I_BASE_COST})
        ON CONFLICT (name) DO NOTHING
        """
    )


def downgrade() -> None:
    # Skip removal if any token_transactions reference this row (FK).
    op.execute(
        """
        DELETE FROM pipeline_types
        WHERE name = 'generative_t2i'
          AND NOT EXISTS (
            SELECT 1 FROM token_transactions tt
            WHERE tt.pipeline_type_id = pipeline_types.id
          )
        """
    )
