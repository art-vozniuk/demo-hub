from pydantic_settings import BaseSettings
from services.common.config.settings import settings as config_settings


class RedisConfig(BaseSettings):
    model_config = config_settings

    URL: str = "redis://redis:6379"
    decode_responses: bool = True
    socket_timeout: int = 5
    socket_connect_timeout: int = 5


redis_config = RedisConfig()
