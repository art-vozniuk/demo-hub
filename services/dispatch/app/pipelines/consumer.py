from services.common.rabbitmq.config import rabbitmq_config
from services.common.rabbitmq.pipeline_worker import PipelineWorker

from services.dispatch.app.pipelines.service import create_service, pipeline_templates


_worker = PipelineWorker(
    pool_name="dispatch",
    queue_name=rabbitmq_config.queue_dispatch,
    pipeline_templates=pipeline_templates,
    create_service=create_service,
)


async def init() -> None:
    await _worker.start()


async def shutdown() -> None:
    await _worker.stop()
