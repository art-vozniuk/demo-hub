"""seed flux pipeline_type

Revision ID: 013
Revises: 012
Create Date: 2026-05-18

"""

from alembic import op


revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


# Same model as generative_editing (FLUX.2 klein on Modal), just exposed
# without preset gating — user supplies the prompt directly. Cost mirrors
# generative_editing since it hits the same GPU path.
FLUX_BASE_COST = 10


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO pipeline_types (name, base_cost)
        VALUES ('flux', {FLUX_BASE_COST})
        ON CONFLICT (name) DO NOTHING
        """
    )


def downgrade() -> None:
    # Skip removal if any token_transactions reference this row (FK).
    op.execute(
        """
        DELETE FROM pipeline_types
        WHERE name = 'flux'
          AND NOT EXISTS (
            SELECT 1 FROM token_transactions tt
            WHERE tt.pipeline_type_id = pipeline_types.id
          )
        """
    )
