from typing import Any

from pydantic import BaseModel


class BalanceResponse(BaseModel):
    # 0 when caller is not authenticated.
    tokens: int
    # name -> base_cost; lets the frontend skip a separate catalog fetch.
    pipeline_costs: dict[str, int]
    # name -> cost_multipliers rule (see pipelines.cost_resolution). Only
    # contains entries for pipelines that have a rule configured;
    # everything else uses base_cost as-is. Mirrored on the frontend so
    # the Quality dropdown can preview the final price without a server
    # round-trip — server-side charge stays authoritative.
    pipeline_cost_multipliers: dict[str, dict[str, Any]]
    # One-time grant a user receives on first sign-in. Exposed so the
    # frontend can render it without hardcoding the number.
    signup_grant: int
