from pydantic_settings import BaseSettings
from services.common.config.settings import settings as config_settings


class Config(BaseSettings):
    model_config = config_settings

    ENV: str
    SENTRY_DSN: str | None = None

    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str | None = None
    ALLOWED_ORIGINS: str

    RATE_LIMIT_QUEUE_PER_MINUTE: int = 100
    RATE_LIMIT_STATUS_PER_MINUTE: int = 5000

    MAX_PIPELINES_PER_REQUEST: int = 3

    # Comma-separated emails allowed to start bench/experiment runs.
    # Server-side enforced on every /api/v1/bench/* endpoint and surfaced
    # to the frontend via /api/v1/me/permissions so the tab can hide
    # for anyone else. Empty string = nobody.
    EXPERIMENT_ALLOWED_EMAILS: str = ""

    # Per-day hard cap on REAL-tier bench spend (USD). The bench
    # coordinator refuses to start a run that would push today's
    # rolling total past this. Mock tiers ignore it.
    BENCH_MAX_DAILY_SPEND_USD: float = 2.0

    # Cost rates per GPU-second (USD). Sourced from Modal's published
    # pricing; only kept here so cost accounting matches what Modal
    # actually bills. Update when prices change.
    GPU_COST_USD_PER_SEC: str = (
        "A10G:0.000306,L4:0.000222,A100-40GB:0.000583,H100:0.001250,CPU:0.0000056"
    )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",")]

    @property
    def experiment_allowed_emails(self) -> set[str]:
        if not self.EXPERIMENT_ALLOWED_EMAILS:
            return set()
        return {
            e.strip().lower()
            for e in self.EXPERIMENT_ALLOWED_EMAILS.split(",")
            if e.strip()
        }

    @property
    def gpu_cost_table(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for entry in self.GPU_COST_USD_PER_SEC.split(","):
            entry = entry.strip()
            if not entry:
                continue
            name, price = entry.split(":")
            out[name.strip()] = float(price)
        return out


config = Config()
