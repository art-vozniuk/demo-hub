"""seed trellis cost multipliers by sampler steps

Revision ID: 019
Revises: 018
Create Date: 2026-05-25

"""

from alembic import op


revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


# 4 / 8 / 12 sampling steps → Low / Standard / High in the UI.
# Multiplier reflects roughly linear sampling time + fixed cold-start
# and export overhead.
PARAMS = (
    '{"input_field": "steps", "values": {"4": 75, "8": 100, "12": 150}}'
)


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO pipeline_cost_multipliers (pipeline_type_id, type, params)
        SELECT id, 'input_field', '{PARAMS}'::jsonb
        FROM pipeline_types
        WHERE name = 'trellis'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM pipeline_cost_multipliers
        WHERE type = 'input_field'
          AND pipeline_type_id = (
            SELECT id FROM pipeline_types WHERE name = 'trellis'
          )
        """
    )
