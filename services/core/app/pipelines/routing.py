"""Maps a pipeline_name to the RabbitMQ routing key its messages should
publish to. Core is otherwise oblivious to what each worker actually
does — only the routing key here decides which pool drains the message.

Two extra concepts on top of the routing table:

- A pool is either *sequential* (one worker drains the queue one job at
  a time — e.g. compute on a single GPU) or *parallel* (each request
  goes to its own worker container — e.g. dispatch → Modal autoscaling).
  ETA estimation needs this distinction: queue depth adds latency in
  sequential pools, but does not in parallel ones.
- Every pipeline name belongs to exactly one pool. ETA for a pipeline
  must only consider in-flight pipelines that share its pool — others
  drain on completely different workers and can't block each other.
"""

from services.common.rabbitmq.config import rabbitmq_config


_ROUTES: dict[str, str] = {
    "face_recognition": rabbitmq_config.routing_compute,
    "face_swap": rabbitmq_config.routing_compute,
    "generative_editing": rabbitmq_config.routing_dispatch,
    "generative_editing_custom": rabbitmq_config.routing_dispatch,
    "sharp": rabbitmq_config.routing_dispatch,
}


# Pools where each request runs in its own worker container in parallel
# (e.g. Modal autoscaling). Queue depth doesn't add latency in these
# pools — ETA is just one inference duration regardless of position.
_PARALLEL_POOLS: set[str] = {rabbitmq_config.routing_dispatch}


def get_routing_key(pipeline_name: str) -> str:
    key = _ROUTES.get(pipeline_name)
    if key is None:
        raise ValueError(f"Unknown pipeline_name: {pipeline_name!r}")
    return key


def known_pipeline_names() -> list[str]:
    return list(_ROUTES.keys())


def is_parallel_pipeline(pipeline_name: str) -> bool:
    """True when this pipeline runs in a pool that scales out per request
    (queue depth doesn't slow you down)."""
    return get_routing_key(pipeline_name) in _PARALLEL_POOLS


def names_in_same_pool(pipeline_name: str) -> set[str]:
    """All pipeline names that share a pool with the given one. Used by
    ETA estimation to ignore in-flight pipelines that drain on a
    different worker pool."""
    pool = get_routing_key(pipeline_name)
    return {name for name, key in _ROUTES.items() if key == pool}
