"""Resolve the final token cost for a queued pipeline.

Each pipeline_type has zero or more rows in `pipeline_cost_multipliers`;
each row's `type` selects a handler and `params` carries its config.
Handlers return a percent multiplier and the resolver composes them
multiplicatively. Integer truncation favours the user; an inactive rule
returns 100 (identity).
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
    """Fetch all multiplier rules for a pipeline_type, ordered by id for
    deterministic composition under non-commutative handlers."""

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
    """Compose the rule percents into the running cost. Unknown handler
    types are skipped (treated as identity) to avoid overcharging on a
    config typo."""

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
