"""seed transcriber pipeline_type + cost multipliers

Revision ID: 021
Revises: 020
Create Date: 2026-08-14

"""

from alembic import op


revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


# A typical 10-minute upload is ~90s on an L4 ($0.80/h) — roughly a third of a
# trellis run, whose 120 is the current compute-priced anchor.
TRANSCRIBER_BASE_COST = 40

# Whisper size is the knob that moves GPU time most: medium is ~2x faster than
# large-v3, turbo sits in between and is the default.
MODEL_PARAMS = (
    '{"input_field": "model", '
    '"values": {"medium": 75, "large-v3-turbo": 100, "large-v3": 150}}'
)

# Cleanup runs one LLM generation per segment on top of the transcript, which
# dominates the run when it is on. Both spellings of the key are listed
# because the multiplier handler stringifies the raw input value: a JSON
# `true` arrives as a Python bool and stringifies to "True", while a client
# sending the string "true" would stringify to "true".
LLM_PARAMS = '{"input_field": "llm_cleanup", "values": {"True": 250, "true": 250}}'


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO pipeline_types (name, base_cost)
        VALUES ('transcriber', {TRANSCRIBER_BASE_COST})
        ON CONFLICT (name) DO NOTHING
        """
    )
    for params in (MODEL_PARAMS, LLM_PARAMS):
        op.execute(
            f"""
            INSERT INTO pipeline_cost_multipliers (pipeline_type_id, type, params)
            SELECT id, 'input_field', '{params}'::jsonb
            FROM pipeline_types
            WHERE name = 'transcriber'
            """
        )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM pipeline_cost_multipliers
        WHERE pipeline_type_id = (
            SELECT id FROM pipeline_types WHERE name = 'transcriber'
        )
        """
    )
    # Skip removal if any token_transactions reference this row (FK).
    op.execute(
        """
        DELETE FROM pipeline_types
        WHERE name = 'transcriber'
          AND NOT EXISTS (
            SELECT 1 FROM token_transactions tt
            WHERE tt.pipeline_type_id = pipeline_types.id
          )
        """
    )
