"""Resolve the final token cost for a queued pipeline.

The wallet layer stays generic: each pipeline_type may have zero or more
rows in `pipeline_cost_multipliers`. Every row carries a `type` (which
handler to dispatch to) and a `params` JSON payload (validated by the
handler's pydantic model). Handlers return a percent multiplier; the
resolver composes them multiplicatively so additional rules can be
added without revisiting existing pricing logic.

Composition example: base 10, rules return [70, 150] → 10 * 70 / 100 *
150 / 100 = 10.5 → 10 (integer truncation favours the user). A handler
that doesn't match the input returns IDENTITY_PCT (100) so the cost is
unaffected by an inactive rule.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..wallet.models import CostMultiplier
from .cost_multipliers import get_handler

log = logging.getLogger(__name__)


async def load_rules(
    db: AsyncSession,
    pipeline_type_id: int,
) -> list[tuple[str, dict[str, Any]]]:
    """Fetch all multiplier rules for a pipeline_type, ordered by id so
    composition is deterministic (matters only for non-commutative
    handlers added in the future)."""

    result = await db.execute(
        select(CostMultiplier.type, CostMultiplier.params)
        .where(CostMultiplier.pipeline_type_id == pipeline_type_id)
        .order_by(CostMultiplier.id)
    )
    return [(t, p) for t, p in result.all()]


def apply_rules(
    base_cost: int,
    rules: list[tuple[str, dict[str, Any]]],
    pipeline_input: dict[str, Any],
) -> int:
    """Walk every rule, multiply the percents into the running cost.
    Unknown handler types are logged and skipped (rule treated as
    identity) — fail open, never overcharge for a config typo."""

    cost = base_cost
    for rule_type, params in rules:
        handler = get_handler(rule_type)
        if handler is None:
            log.warning(
                f"unknown cost_multiplier type {rule_type!r}; treating as identity"
            )
            continue
        pct = handler.resolve(params or {}, pipeline_input)
        cost = max(0, cost * pct // 100)
    return cost


async def resolve_cost(
    db: AsyncSession,
    pipeline_type_id: int,
    base_cost: int,
    pipeline_input: dict[str, Any],
) -> int:
    rules = await load_rules(db, pipeline_type_id)
    final = apply_rules(base_cost, rules, pipeline_input)
    log.info(
        f"resolve_cost: pipeline_type_id={pipeline_type_id} "
        f"base={base_cost} rules={len(rules)} input={pipeline_input!r} "
        f"final={final}"
    )
    return final
