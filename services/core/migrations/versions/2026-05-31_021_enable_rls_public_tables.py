"""enable Row Level Security on all public application tables

Closes the Supabase "RLS disabled in public schema" advisory. Without RLS
every table in `public` is reachable by the `anon` / `authenticated`
PostgREST roles — i.e. anyone holding the public anon key could read or
modify every row (including token_transactions balances and pipeline data).

This app never touches these tables through PostgREST: the web client uses
Supabase only for auth, and every backend service connects directly over
asyncpg as the `postgres` role, which has BYPASSRLS. Enabling RLS therefore
locks out the public REST surface while leaving all backend access intact —
no policies are required for current functionality.

If a table is later meant to be exposed directly to anon/authenticated
clients, add explicit policies for it; until then the default deny is the
desired behaviour.

Revision ID: 021
Revises: 020
Create Date: 2026-05-31

"""

from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


# Every table living in the public schema. Ordering is irrelevant — each
# statement is independent and idempotent.
TABLES = [
    "alembic_version",
    "recast_templates",
    "pipelines",
    "splat_scenes",
    "generative_presets",
    "pipeline_types",
    "token_transactions",
    "pipeline_cost_multipliers",
    "editor_scenes",
]


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
