import pytest

from services.core.app.pipelines.routing import (
    get_route,
    known_pipeline_names,
)
from services.common.rabbitmq.config import rabbitmq_config


def test_face_swap_routes_to_compute_pool():
    route = get_route("face_swap")
    assert route.pool == "compute"
    assert route.routing_key == rabbitmq_config.routing_submit


def test_generative_editing_routes_to_dispatch_pool():
    route = get_route("generative_editing")
    assert route.pool == "dispatch"
    assert route.routing_key == rabbitmq_config.routing_dispatch


def test_unknown_pipeline_raises():
    with pytest.raises(ValueError):
        get_route("nope")


def test_known_pipeline_names_contains_all():
    names = known_pipeline_names()
    assert "face_recognition" in names
    assert "face_swap" in names
    assert "generative_editing" in names
