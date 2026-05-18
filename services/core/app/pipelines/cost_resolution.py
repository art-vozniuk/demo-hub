"""Generic input-driven cost scaling for queued pipelines.

A pipeline_types row may carry a `cost_multipliers` rule describing how
its `base_cost` scales with the input payload. The rule shape is:

    {
        "input_field": "<key in pipeline.input>",
        "values": {"<value>": <percent>, ...}
    }

`<percent>` is an integer where 100 means "charge base_cost". Final
cost = base_cost * percent / 100. Input values are matched as strings so
the rule survives JSON serialization (e.g. {"2": 70} matches both
`num_inference_steps: 2` and `num_inference_steps: "2"`).

If no rule is configured, or the input value isn't in the table, we fall
back to `base_cost` — a missing entry never overcharges the user.

This keeps wallet code free of per-pipeline branches: each pipeline
declares its scaling in data (a migration), not in code.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def resolve_cost(
    base_cost: int,
    rule: dict[str, Any] | None,
    pipeline_input: dict[str, Any],
) -> int:
    if not rule:
        return base_cost

    field = rule.get("input_field")
    values = rule.get("values")
    if not field or not isinstance(values, dict) or not values:
        log.warning(f"cost_multipliers malformed; falling back to base: {rule!r}")
        return base_cost

    raw_value = pipeline_input.get(field)
    if raw_value is None:
        return base_cost

    pct = values.get(str(raw_value))
    if pct is None:
        return base_cost

    try:
        pct_int = int(pct)
    except (TypeError, ValueError):
        log.warning(f"cost_multipliers percent {pct!r} is not an int; using base")
        return base_cost

    return max(0, base_cost * pct_int // 100)
