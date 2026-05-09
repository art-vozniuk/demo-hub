"""Maps a pipeline_name to the queue/worker pool that drains it.

Core itself stays oblivious to what each worker actually does — it only
needs to know which routing key to publish under and which `pool` label
the workers in question heartbeat under (so ETA math can use the right
parallelism + duration history).
"""

from dataclasses import dataclass

from services.common.rabbitmq.config import rabbitmq_config


@dataclass(frozen=True)
class PipelineRoute:
    routing_key: str
    pool: str
    fallback_duration_ms: float


# `fallback_duration_ms` is what we report as "average duration" before any
# real samples have been recorded — picked from rough empirical wall-time
# of one inference end-to-end, used so that first-ever ETAs don't read 0s.
_ROUTES: dict[str, PipelineRoute] = {
    "face_recognition": PipelineRoute(
        routing_key=rabbitmq_config.routing_submit,
        pool="compute",
        fallback_duration_ms=2_000,
    ),
    "face_swap": PipelineRoute(
        routing_key=rabbitmq_config.routing_submit,
        pool="compute",
        fallback_duration_ms=8_000,
    ),
    "generative_editing": PipelineRoute(
        routing_key=rabbitmq_config.routing_dispatch,
        pool="dispatch",
        fallback_duration_ms=25_000,
    ),
}


def get_route(pipeline_name: str) -> PipelineRoute:
    route = _ROUTES.get(pipeline_name)
    if route is None:
        raise ValueError(f"Unknown pipeline_name: {pipeline_name!r}")
    return route


def known_pipeline_names() -> list[str]:
    return list(_ROUTES.keys())
