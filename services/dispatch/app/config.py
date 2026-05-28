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

    # Per-HTTP-call timeout (submit, one poll). Short so we surface a
    # hung Modal-gateway fast and retry it.
    MODAL_REQUEST_TIMEOUT_SECONDS: int = 30
    # End-to-end pipeline deadline: how long _submit_and_poll will keep
    # polling before giving up. Sized for the slowest pipeline (TRELLIS
    # image-to-3D: ~3 min warm, plus cold restore overhead).
    MODAL_PIPELINE_DEADLINE_SECONDS: int = 600
    MODAL_POLL_INTERVAL_SECONDS: float = 2.0

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

    # Optimised FLUX deployment (services/modal/flux_opt). Each (gpu, batch)
    # variant is its own deployment so per-config billing in the Modal UI
    # stays separable. URLs are written by services/modal/flux_opt/deploy.py.
    MODAL_FLUX_OPT_A10G_SUBMIT_URL: str | None = None
    MODAL_FLUX_OPT_A10G_POLL_URL: str | None = None
    MODAL_FLUX_OPT_H100_SUBMIT_URL: str | None = None
    MODAL_FLUX_OPT_H100_POLL_URL: str | None = None


config = Config()
