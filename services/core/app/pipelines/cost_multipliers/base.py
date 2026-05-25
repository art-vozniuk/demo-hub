"""Cost-multiplier handler contract.

A handler reads its validated `params` plus the pipeline input and
returns a percent multiplier (100 = identity). Results compose
multiplicatively, so handlers that don't recognise the input MUST
return IDENTITY_PCT — never silently discount or upcharge.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)


IDENTITY_PCT = 100


class CostMultiplierHandler:
    # type_id: row's `type` value in pipeline_cost_multipliers.
    # params_model: pydantic validator for the row's `params`.
    type_id: ClassVar[str]
    params_model: ClassVar[type[BaseModel]]

    def parse_params(self, raw: dict[str, Any]) -> BaseModel | None:
        """Validate raw JSON params; returns None on failure so the
        resolver skips the rule rather than overcharging."""
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
        """Return a percent multiplier; IDENTITY_PCT when the rule does
        not apply to this input."""
        raise NotImplementedError
