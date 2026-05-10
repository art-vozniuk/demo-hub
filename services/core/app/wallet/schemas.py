from pydantic import BaseModel


class BalanceResponse(BaseModel):
    tokens: int
    is_anonymous: bool
    # name -> base_cost; lets the frontend skip a separate catalog fetch.
    pipeline_costs: dict[str, int]
