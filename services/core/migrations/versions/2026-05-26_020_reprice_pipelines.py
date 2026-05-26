"""reprice trellis and generative_t2i

Revision ID: 020
Revises: 019
Create Date: 2026-05-26

"""

from alembic import op


revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


# Rebalanced after measuring real Modal compute cost per pipeline.
# Klein (generative_editing_custom) stays at 10 as the anchor; the others
# scale proportionally to compute and keep room for a margin.
NEW_T2I_BASE = 25
OLD_T2I_BASE = 10
NEW_TRELLIS_BASE = 120
OLD_TRELLIS_BASE = 20


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE pipeline_types
        SET base_cost = {NEW_T2I_BASE}
        WHERE name = 'generative_t2i'
        """
    )
    op.execute(
        f"""
        UPDATE pipeline_types
        SET base_cost = {NEW_TRELLIS_BASE}
        WHERE name = 'trellis'
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE pipeline_types
        SET base_cost = {OLD_T2I_BASE}
        WHERE name = 'generative_t2i'
        """
    )
    op.execute(
        f"""
        UPDATE pipeline_types
        SET base_cost = {OLD_TRELLIS_BASE}
        WHERE name = 'trellis'
        """
    )
