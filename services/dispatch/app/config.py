from pydantic_settings import BaseSettings
from services.common import constants
from services.common.config.settings import settings as config_settings


class Config(BaseSettings):
    model_config = config_settings

    ENV: str = "local"
    SENTRY_DSN: str | None = None

    # Modal proxy-auth token (Modal-Key/Modal-Secret on requires_proxy_auth).
    MODAL_PROXY_AUTH_TOKEN_ID: str | None = None
    MODAL_PROXY_AUTH_TOKEN_SECRET: str | None = None

    # Per-HTTP-call timeout (submit, one poll). Short so we surface a
    # hung Modal-gateway fast and retry it.
    MODAL_REQUEST_TIMEOUT_SECONDS: int = 30
    # End-to-end pipeline deadline: how long _submit_and_poll will keep
    # polling before giving up. Default comes from the shared constants
    # module — it must stay equal to the Modal function timeout and the
    # top histogram bucket, so override with care.
    MODAL_PIPELINE_DEADLINE_SECONDS: int = constants.MODAL_PIPELINE_DEADLINE_SECONDS
    MODAL_POLL_INTERVAL_SECONDS: float = constants.MODAL_POLL_INTERVAL_SECONDS

    # Transient HTTP errors against Modal-gateway are retried in-place
    # inside _post_to_modal — that way a single 502 doesn't unwind the
    # whole pipeline back to RabbitMQ (which would re-spawn a new Modal
    # call from scratch and re-charge cold start).
    MODAL_RETRY_MAX_ATTEMPTS: int = 5
    MODAL_RETRY_BASE_DELAY_MS: int = 500
    MODAL_RETRY_MAX_DELAY_MS: int = 4000

    # Single shared httpx.AsyncClient across the whole worker; keep the
    # pool generous so the worker's prefetch=256 doesn't choke on TCP
    # handshake churn under burst load.
    MODAL_HTTP_POOL_KEEPALIVE: int = 128
    MODAL_HTTP_POOL_MAX: int = 256

    # Single Modal web gateway (services/modal/gateway) fronts every model
    # — one submit/poll pair, routed by payload["model"]. Keeps us under the
    # free-tier web-function cap. URLs written by gateway/deploy.py.
    MODAL_GATEWAY_SUBMIT_URL: str | None = None
    MODAL_GATEWAY_POLL_URL: str | None = None


config = Config()
