"""Maps a pipeline_name to the RabbitMQ routing key its messages should
publish to. Core is otherwise oblivious to what each worker actually
does — only the routing key here decides which pool drains the message.

ETA estimation is intentionally pipeline-name-agnostic (see
services/core/app/pipelines/estimation.py): it just sums per-worker
heartbeat durations grouped by pipeline_name across the whole platform.
That keeps this module a pure routing table.
"""

from services.common.rabbitmq.config import rabbitmq_config


_ROUTES: dict[str, str] = {
    "face_recognition": rabbitmq_config.routing_submit,
    "face_swap": rabbitmq_config.routing_submit,
    "generative_editing": rabbitmq_config.routing_dispatch,
}


def get_routing_key(pipeline_name: str) -> str:
    key = _ROUTES.get(pipeline_name)
    if key is None:
        raise ValueError(f"Unknown pipeline_name: {pipeline_name!r}")
    return key


def known_pipeline_names() -> list[str]:
    return list(_ROUTES.keys())
