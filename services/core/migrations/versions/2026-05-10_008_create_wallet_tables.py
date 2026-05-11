"""create pipeline_types and token_transactions

Revision ID: 008
Revises: 007
Create Date: 2026-05-10

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


# Seed costs (routing keys still come from routing.py).
PIPELINE_TYPES = [
    ("face_recognition", 0),
    ("face_swap", 1),
    ("generative_editing", 10),
]


def upgrade() -> None:
    op.create_table(
        "pipeline_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("base_cost", sa.Integer(), nullable=False),
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
        sa.UniqueConstraint("name", name="uq_pipeline_types_name"),
        sa.CheckConstraint("base_cost >= 0", name="ck_pipeline_types_base_cost_nonneg"),
    )

    pipeline_types_tbl = sa.table(
        "pipeline_types",
        sa.column("name", sa.String()),
        sa.column("base_cost", sa.Integer()),
    )
    op.bulk_insert(
        pipeline_types_tbl,
        [{"name": n, "base_cost": c} for n, c in PIPELINE_TYPES],
    )

    op.create_table(
        "token_transactions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("anon_id", UUID(as_uuid=True), nullable=True),
        sa.Column("pipeline_id", UUID(as_uuid=True), nullable=True),
        sa.Column("pipeline_type_id", sa.Integer(), nullable=True),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["pipeline_type_id"],
            ["pipeline_types.id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "user_id IS NOT NULL OR anon_id IS NOT NULL",
            name="ck_token_transactions_owner",
        ),
        sa.CheckConstraint(
            "reason IN ('signup_grant','anon_grant','charge','refund','anon_migration')",
            name="ck_token_transactions_reason",
        ),
    )

    op.create_index(
        "ix_token_transactions_user_id_created_at",
        "token_transactions",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_token_transactions_anon_id_created_at",
        "token_transactions",
        ["anon_id", "created_at"],
    )
    op.create_index(
        "ix_token_transactions_pipeline_id",
        "token_transactions",
        ["pipeline_id"],
    )

    # Idempotency: at most one charge and one refund per pipeline_id.
    op.create_index(
        "uq_token_transactions_pipeline_reason",
        "token_transactions",
        ["pipeline_id", "reason"],
        unique=True,
        postgresql_where=sa.text("pipeline_id IS NOT NULL"),
    )
    # Idempotency: at most one signup_grant per user.
    op.create_index(
        "uq_token_transactions_user_signup_grant",
        "token_transactions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("reason = 'signup_grant' AND user_id IS NOT NULL"),
    )
    # Idempotency: at most one anon_grant per anon cookie.
    op.create_index(
        "uq_token_transactions_anon_initial_grant",
        "token_transactions",
        ["anon_id"],
        unique=True,
        postgresql_where=sa.text("reason = 'anon_grant' AND anon_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_token_transactions_anon_initial_grant",
        table_name="token_transactions",
    )
    op.drop_index(
        "uq_token_transactions_user_signup_grant",
        table_name="token_transactions",
    )
    op.drop_index(
        "uq_token_transactions_pipeline_reason",
        table_name="token_transactions",
    )
    op.drop_index("ix_token_transactions_pipeline_id", table_name="token_transactions")
    op.drop_index(
        "ix_token_transactions_anon_id_created_at",
        table_name="token_transactions",
    )
    op.drop_index(
        "ix_token_transactions_user_id_created_at",
        table_name="token_transactions",
    )
    op.drop_table("token_transactions")
    op.drop_table("pipeline_types")
