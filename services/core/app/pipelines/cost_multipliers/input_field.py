"""Multiplier keyed on the value of a single pipeline input field.

Example: scale FLUX cost by `num_inference_steps`. The migration row
looks like:

    type = 'input_field'
    params = {"input_field": "num_inference_steps",
              "values": {"2": 70, "4": 100, "8": 150}}

Values are matched as strings so JSON-serialised numbers and strings
both work. An input value not listed in the table maps to IDENTITY_PCT
(never overcharge for an unknown bucket).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .base import IDENTITY_PCT, CostMultiplierHandler


class InputFieldParams(BaseModel):
    input_field: str = Field(min_length=1)
    # value (stringified at the source) -> percent multiplier (100 = no-op).
    values: dict[str, int]


class InputFieldHandler(CostMultiplierHandler):
    type_id = "input_field"
    params_model = InputFieldParams

    def resolve(
        self,
        params: dict[str, Any],
        pipeline_input: dict[str, Any],
    ) -> int:
        parsed = self.parse_params(params)
        if parsed is None:
            return IDENTITY_PCT
        assert isinstance(parsed, InputFieldParams)

        raw = pipeline_input.get(parsed.input_field)
        if raw is None:
            return IDENTITY_PCT
        return parsed.values.get(str(raw), IDENTITY_PCT)
