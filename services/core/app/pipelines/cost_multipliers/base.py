"""Cost-multiplier handler contract.

A handler reads its handler-specific `params` (validated through its
own pydantic model) plus the queued pipeline `input`, and returns a
percent multiplier — an int where 100 means "no change". The cost
resolver multiplies all handler results together (multiplicative
composition), so a handler that doesn't recognise the input must
return IDENTITY_PCT so it doesn't accidentally discount or upcharge.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)


IDENTITY_PCT = 100


class CostMultiplierHandler:
    # Subclasses set a unique string id (used as the `type` value in the
    # pipeline_cost_multipliers table) and a pydantic model that
    # validates the row's `params` payload.
    type_id: ClassVar[str]
    params_model: ClassVar[type[BaseModel]]

    def parse_params(self, raw: dict[str, Any]) -> BaseModel | None:
        """Validate the raw JSON payload against `params_model`. Returns
        None and logs on validation failure — the resolver then skips
        the rule rather than overcharging."""
        try:
            return self.params_model.model_validate(raw)
        except ValidationError as e:
            log.warning(
                f"cost_multiplier {self.type_id!r} params invalid; skipping: {e}"
            )
            return None

    def resolve(
        self,
        params: dict[str, Any],
        pipeline_input: dict[str, Any],
    ) -> int:
        """Return a percent multiplier (100 = identity). Must return
        IDENTITY_PCT when this rule doesn't apply to the given input —
        never silently overcharge."""
        raise NotImplementedError
