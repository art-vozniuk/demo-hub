import logging

from enum import StrEnum
from pydantic_settings import BaseSettings

from services.common.config.settings import settings as config_settings

LOG_FORMAT_DEBUG = "%(levelname)s: %(message)s (%(pathname)s:%(funcName)s:%(lineno)d)"


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

    if config.LOG_LEVEL == LogLevels.debug:
        logging.basicConfig(level=LogLevels.debug, format=LOG_FORMAT_DEBUG)
        return

    logging.basicConfig(level=config.LOG_LEVEL)
