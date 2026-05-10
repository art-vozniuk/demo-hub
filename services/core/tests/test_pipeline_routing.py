import pytest

from services.core.app.pipelines.routing import (
    get_routing_key,
    known_pipeline_names,
)
from services.common.rabbitmq.config import rabbitmq_config


def test_face_swap_routes_to_compute_queue():
    assert get_routing_key("face_swap") == rabbitmq_config.routing_compute


def test_face_recognition_routes_to_compute_queue():
    assert get_routing_key("face_recognition") == rabbitmq_config.routing_compute


def test_generative_editing_routes_to_dispatch_queue():
    assert get_routing_key("generative_editing") == rabbitmq_config.routing_dispatch


def test_unknown_pipeline_raises():
    with pytest.raises(ValueError):
        get_routing_key("nope")


def test_known_pipeline_names_contains_all():
    names = known_pipeline_names()
    assert "face_recognition" in names
    assert "face_swap" in names
    assert "generative_editing" in names
