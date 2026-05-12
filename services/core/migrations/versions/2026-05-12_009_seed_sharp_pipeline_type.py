"""seed sharp pipeline_type

Adds a `pipeline_types` row for the SHARP demo so the wallet charge step
at /pipelines/queue can resolve a price for it. Idempotent INSERT —
re-running the migration on a DB that already has the row is a no-op.

Revision ID: 009
Revises: 008
Create Date: 2026-05-12

"""

from alembic import op


revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


# Same ballpark as generative_editing (10) since SHARP is similarly a
# GPU forward-pass demo. Tune later from observed Modal costs.
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
    # Skip removal if any token_transactions reference this pipeline_type —
    # avoids a FK violation on rollback in environments that have already
    # served traffic.
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
