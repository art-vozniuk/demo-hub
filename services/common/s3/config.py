from pydantic_settings import BaseSettings
from services.common.config.settings import settings as config_settings


class Config(BaseSettings):
    model_config = config_settings

    S3_ACCESS_KEY_ID: str
    S3_ACCESS_KEY_SECRET: str
    S3_ENDPOINT: str
    S3_PUBLIC_BUCKETS_ENDPOINT: str
    S3_REGION: str


config = Config()
