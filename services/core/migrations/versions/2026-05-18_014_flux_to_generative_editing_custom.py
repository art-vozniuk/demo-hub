"""rename flux to generative_editing_custom and add cost_multipliers

Revision ID: 014
Revises: 013
Create Date: 2026-05-18

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Generic variable-pricing hook: cost = base_cost * pct / 100, where
    # `pct` is looked up by an input field value. NULL = no rule = charge
    # base_cost as-is. Keeps wallet code free of per-pipeline branches —
    # each pipeline declares its scaling in data, not code.
    op.add_column(
        "pipeline_types",
        sa.Column("cost_multipliers", JSONB, nullable=True),
    )

    # Rename: 013 introduced `flux` before this feature shipped to prod,
    # so the row is renamed in place. id is stable → FK from
    # token_transactions stays intact.
    op.execute(
        """
        UPDATE pipeline_types
        SET name = 'generative_editing_custom'
        WHERE name = 'flux'
        """
    )

    # Fast/Standard/High → 70/100/150 % of base_cost. Mirrors the
    # roughly-linear scaling of FLUX.2 klein inference time with steps,
    # softened by fixed cold-start / IO overhead. UI displays multipliers
    # in the Quality dropdown so the user sees what they're paying for.
    op.execute(
        """
        UPDATE pipeline_types
        SET cost_multipliers = '{"input_field": "num_inference_steps", "values": {"2": 70, "4": 100, "8": 150}}'::jsonb
        WHERE name = 'generative_editing_custom'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE pipeline_types
        SET name = 'flux', cost_multipliers = NULL
        WHERE name = 'generative_editing_custom'
        """
    )
    op.drop_column("pipeline_types", "cost_multipliers")
