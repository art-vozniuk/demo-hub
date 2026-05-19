"""normalize cost_multipliers into a stackable rules table

Revision ID: 015
Revises: 014
Create Date: 2026-05-18

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One row per rule. Multiple rules per pipeline_type compose
    # multiplicatively (see services/core/app/pipelines/cost_resolution).
    # `type` selects the handler, `params` is the handler-specific
    # payload — each handler ships its own pydantic model and validates
    # what it reads, so the column itself stays handler-agnostic.
    op.create_table(
        "pipeline_cost_multipliers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pipeline_type_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("params", JSONB, nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["pipeline_type_id"],
            ["pipeline_types.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_pipeline_cost_multipliers_pipeline_type_id",
        "pipeline_cost_multipliers",
        ["pipeline_type_id"],
    )

    # Migrate the single rule that 014 stuffed into pipeline_types.cost_multipliers.
    # `type='input_field'` is the only handler that exists today; the JSON
    # payload moves over unchanged.
    op.execute(
        """
        INSERT INTO pipeline_cost_multipliers (pipeline_type_id, type, params)
        SELECT id, 'input_field', cost_multipliers
        FROM pipeline_types
        WHERE cost_multipliers IS NOT NULL
        """
    )

    op.drop_column("pipeline_types", "cost_multipliers")


def downgrade() -> None:
    op.add_column(
        "pipeline_types",
        sa.Column("cost_multipliers", JSONB, nullable=True),
    )
    # Best-effort restore: a multi-rule setup can't round-trip into a
    # single JSON column. We keep the first input_field rule per
    # pipeline_type; anything else is dropped on downgrade.
    op.execute(
        """
        UPDATE pipeline_types pt
        SET cost_multipliers = sub.params
        FROM (
            SELECT DISTINCT ON (pipeline_type_id)
                pipeline_type_id, params
            FROM pipeline_cost_multipliers
            WHERE type = 'input_field'
            ORDER BY pipeline_type_id, id ASC
        ) sub
        WHERE pt.id = sub.pipeline_type_id
        """
    )
    op.drop_index(
        "ix_pipeline_cost_multipliers_pipeline_type_id",
        table_name="pipeline_cost_multipliers",
    )
    op.drop_table("pipeline_cost_multipliers")
