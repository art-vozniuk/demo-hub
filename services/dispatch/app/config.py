from pydantic_settings import BaseSettings
from services.common.config.settings import settings as config_settings


class Config(BaseSettings):
    model_config = config_settings

    ENV: str = "local"
    SENTRY_DSN: str | None = None

    # Every Modal app exposes a submit + poll endpoint pair (uniform shape,
    # also dodges Modal's ~60s sync gateway cap on cold starts).
    MODAL_GENERATIVE_SUBMIT_URL: str | None = None
    MODAL_GENERATIVE_POLL_URL: str | None = None
    MODAL_GENERATIVE_T2I_SUBMIT_URL: str | None = None
    MODAL_GENERATIVE_T2I_POLL_URL: str | None = None
    MODAL_SHARP_SUBMIT_URL: str | None = None
    MODAL_SHARP_POLL_URL: str | None = None
    MODAL_TRELLIS_SUBMIT_URL: str | None = None
    MODAL_TRELLIS_POLL_URL: str | None = None
    MODAL_PROXY_AUTH_TOKEN_ID: str | None = None
    MODAL_PROXY_AUTH_TOKEN_SECRET: str | None = None

    # End-to-end Modal call ceiling, sized for the slowest pipeline
    # (TRELLIS image-to-3D: ~3 min warm, plus cold restore overhead).
    MODAL_REQUEST_TIMEOUT_SECONDS: int = 600
    MODAL_POLL_INTERVAL_SECONDS: float = 2.0


config = Config()
