from pydantic_settings import BaseSettings
from services.common.config.settings import settings as config_settings


class Config(BaseSettings):
    model_config = config_settings

    ENV: str = "local"
    SENTRY_DSN: str | None = None

    MODAL_GENERATIVE_ENDPOINT_URL: str | None = None
    MODAL_SHARP_ENDPOINT_URL: str | None = None
    MODAL_PROXY_AUTH_TOKEN_ID: str | None = None
    MODAL_PROXY_AUTH_TOKEN_SECRET: str | None = None

    # End-to-end Modal call ceiling. Klein 4B is fast (~sub-second
    # inference, 4 steps), but cold start + first GPU upload can take
    # 30-60s; we leave plenty of headroom.
    MODAL_REQUEST_TIMEOUT_SECONDS: int = 240


config = Config()
