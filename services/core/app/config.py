from pydantic_settings import BaseSettings
from services.common.config.settings import settings as config_settings


class Config(BaseSettings):
    model_config = config_settings

    ENV: str
    SENTRY_DSN: str | None = None

    SUPABASE_URL: str
    ALLOWED_ORIGINS: str

    RATE_LIMIT_QUEUE_PER_MINUTE: int = 5
    RATE_LIMIT_STATUS_PER_MINUTE: int = 600

    MAX_PIPELINES_PER_REQUEST: int = 6

    TEST_USER_EMAIL: str | None = None

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",")]


config = Config()
