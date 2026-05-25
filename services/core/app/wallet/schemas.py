from pydantic import BaseModel


class BalanceResponse(BaseModel):
    # 0 when caller is not authenticated.
    tokens: int
    # name -> base_cost. Variable-priced pipelines must hit
    # POST /pipelines/cost-preview for the input-aware final cost.
    pipeline_costs: dict[str, int]
    # One-time grant a user receives on first sign-in.
    signup_grant: int
