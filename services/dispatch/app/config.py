from pydantic_settings import BaseSettings
from services.common.config.settings import settings as config_settings


class Config(BaseSettings):
    model_config = config_settings

    ENV: str = "local"
    SENTRY_DSN: str | None = None

    MODAL_GENERATIVE_ENDPOINT_URL: str | None = None
    MODAL_PROXY_AUTH_TOKEN_ID: str | None = None
    MODAL_PROXY_AUTH_TOKEN_SECRET: str | None = None

    # End-to-end Modal call ceiling. Cold start + inference for FLUX.2
    # klein on A10G runs ~30-60s; we leave plenty of headroom.
    MODAL_REQUEST_TIMEOUT_SECONDS: int = 240

    # Core's HTTP service-to-service URL on the docker network. Used to
    # resolve preset slugs to the hidden prompt template.
    CORE_INTERNAL_URL: str = "http://core:8081"


config = Config()
