import os
from pydantic import Field
from pydantic_settings import BaseSettings


class RabbitMQConfig(BaseSettings):
    url: str = Field(
        default_factory=lambda: os.getenv(
            "RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/"
        )
    )

    exchange: str = Field(
        default_factory=lambda: os.getenv("RABBITMQ_EXCHANGE", "pipelines.exchange")
    )
    dlx: str = Field(default_factory=lambda: os.getenv("RABBITMQ_DLX", "pipelines.dlx"))

    queue_main: str = Field(
        default_factory=lambda: os.getenv("RABBITMQ_QUEUE_MAIN", "pipelines.queue")
    )
    queue_update: str = Field(
        default_factory=lambda: os.getenv("RABBITMQ_QUEUE_UPDATE", "pipelines.update")
    )
    queue_main_dlq: str = Field(
        default_factory=lambda: os.getenv(
            "RABBITMQ_QUEUE_MAIN_DLQ", "pipelines.queue.dlq"
        )
    )
    queue_update_dlq: str = Field(
        default_factory=lambda: os.getenv(
            "RABBITMQ_QUEUE_UPDATE_DLQ", "pipelines.update.dlq"
        )
    )

    routing_submit: str = Field(
        default_factory=lambda: os.getenv("RABBITMQ_ROUTING_SUBMIT", "pipelines.submit")
    )
    routing_update: str = Field(
        default_factory=lambda: os.getenv("RABBITMQ_ROUTING_UPDATE", "pipelines.update")
    )

    prefetch: int = Field(
        default_factory=lambda: int(os.getenv("RABBITMQ_PREFETCH", "1"))
    )
    publish_confirm_timeout: int = Field(
        default_factory=lambda: int(os.getenv("RABBITMQ_PUBLISH_CONFIRM_TIMEOUT", "5"))
    )
    retry_max: int = Field(
        default_factory=lambda: int(os.getenv("RABBITMQ_RETRY_MAX", "5"))
    )
    retry_backoff_ms: int = Field(
        default_factory=lambda: int(os.getenv("RABBITMQ_RETRY_BACKOFF_MS", "250"))
    )


rabbitmq_config = RabbitMQConfig()
