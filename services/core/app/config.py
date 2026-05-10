from pydantic_settings import BaseSettings
from services.common.config.settings import settings as config_settings


class Config(BaseSettings):
    model_config = config_settings

    ENV: str
    SENTRY_DSN: str | None = None

    SUPABASE_URL: str
    ALLOWED_ORIGINS: str

    RATE_LIMIT_QUEUE_PER_MINUTE: int = 100
    RATE_LIMIT_STATUS_PER_MINUTE: int = 5000

    MAX_PIPELINES_PER_REQUEST: int = 3

    # HMAC for the anon-wallet cookie. Unset disables the anon tier.
    WALLET_COOKIE_SECRET: str | None = None

    # Cloudflare Turnstile server secret. Unset skips verification (dev).
    TURNSTILE_SECRET: str | None = None

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",")]


config = Config()
