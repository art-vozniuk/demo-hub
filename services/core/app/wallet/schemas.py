from pydantic import BaseModel


class BalanceResponse(BaseModel):
    tokens: int
    is_anonymous: bool
    # name -> base_cost; lets the frontend skip a separate catalog fetch.
    pipeline_costs: dict[str, int]
    # True when backend will reject anon /pipelines/queue without a
    # Turnstile token. Frontend uses this to decide whether to load the
    # widget at all — avoids CSP/sandbox noise in local dev.
    turnstile_required: bool
