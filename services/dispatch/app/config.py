from pydantic_settings import BaseSettings
from services.common.config.settings import settings as config_settings


class Config(BaseSettings):
    model_config = config_settings

    ENV: str = "local"
    SENTRY_DSN: str | None = None

    MODAL_GENERATIVE_ENDPOINT_URL: str | None = None
    # SHARP uses a submit+poll pair to dodge Modal's ~60s sync gateway cap.
    MODAL_SHARP_SUBMIT_URL: str | None = None
    MODAL_SHARP_POLL_URL: str | None = None
    MODAL_PROXY_AUTH_TOKEN_ID: str | None = None
    MODAL_PROXY_AUTH_TOKEN_SECRET: str | None = None

    # End-to-end Modal call ceiling. Klein 4B is fast (~sub-second
    # inference, 4 steps), but cold start + first GPU upload can take
    # 30-60s; we leave plenty of headroom.
    MODAL_REQUEST_TIMEOUT_SECONDS: int = 240
    MODAL_POLL_INTERVAL_SECONDS: float = 2.0


config = Config()
