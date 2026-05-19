from pydantic import BaseModel


class BalanceResponse(BaseModel):
    # 0 when caller is not authenticated.
    tokens: int
    # name -> base_cost; lets the frontend skip a separate catalog fetch.
    # Final cost for pipelines with variable pricing comes from
    # POST /pipelines/cost-preview, not from this map.
    pipeline_costs: dict[str, int]
    # One-time grant a user receives on first sign-in. Exposed so the
    # frontend can render it without hardcoding the number.
    signup_grant: int
