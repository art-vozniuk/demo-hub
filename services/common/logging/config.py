import logging
from contextvars import ContextVar

from enum import StrEnum
from pydantic_settings import BaseSettings

from services.common.config.settings import settings as config_settings

LOG_FORMAT_DEBUG = "%(levelname)s: %(message)s (%(pathname)s:%(funcName)s:%(lineno)d)"

context_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
context_pipeline_id: ContextVar[str | None] = ContextVar("pipeline_id", default=None)
context_user_id: ContextVar[str | None] = ContextVar("user_id", default=None)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = {
            "trace_id": context_trace_id.get(),
            "pipeline_id": context_pipeline_id.get(),
            "user_id": context_user_id.get(),
        }

        context_str = " ".join(f"[{k}={v}]" for k, v in context.items() if v)
        if context_str:
            record.msg = f"{record.msg} {context_str}"
            record.args = None  # clear args to prevent formatting issues

        return True


class LogLevels(StrEnum):
    info = "INFO"
    warn = "WARN"
    error = "ERROR"
    debug = "DEBUG"


class Config(BaseSettings):
    model_config = config_settings

    LOG_LEVEL: str = LogLevels.info


def configure():
    config = Config()

    handler = logging.StreamHandler()
    handler.addFilter(ContextFilter())

    root = logging.getLogger()
    root.setLevel(config.LOG_LEVEL)
    root.addHandler(handler)

    logging.basicConfig(handlers=[handler], force=True)
