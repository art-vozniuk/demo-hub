import pytest

from services.core.app.pipelines.routing import (
    get_routing_key,
    is_parallel_pipeline,
    known_pipeline_names,
    names_in_same_pool,
)
from services.common.rabbitmq.config import rabbitmq_config


def test_face_swap_routes_to_compute_queue():
    assert get_routing_key("face_swap") == rabbitmq_config.routing_compute


def test_face_recognition_routes_to_compute_queue():
    assert get_routing_key("face_recognition") == rabbitmq_config.routing_compute


def test_generative_editing_routes_to_dispatch_queue():
    assert get_routing_key("generative_editing") == rabbitmq_config.routing_dispatch


def test_sharp_routes_to_dispatch_queue():
    assert get_routing_key("sharp") == rabbitmq_config.routing_dispatch


def test_generative_editing_custom_routes_to_dispatch_queue():
    assert (
        get_routing_key("generative_editing_custom") == rabbitmq_config.routing_dispatch
    )


def test_generative_t2i_routes_to_dispatch_queue():
    assert get_routing_key("generative_t2i") == rabbitmq_config.routing_dispatch


def test_trellis_routes_to_dispatch_queue():
    assert get_routing_key("trellis") == rabbitmq_config.routing_dispatch


def test_unknown_pipeline_raises():
    with pytest.raises(ValueError):
        get_routing_key("nope")


def test_known_pipeline_names_contains_all():
    names = known_pipeline_names()
    assert "face_recognition" in names
    assert "face_swap" in names
    assert "generative_editing" in names
    assert "sharp" in names
    assert "generative_editing_custom" in names
    assert "generative_t2i" in names
    assert "trellis" in names


def test_compute_pool_is_sequential():
    assert is_parallel_pipeline("face_swap") is False
    assert is_parallel_pipeline("face_recognition") is False


def test_dispatch_pool_is_parallel():
    assert is_parallel_pipeline("generative_editing") is True
    assert is_parallel_pipeline("sharp") is True
    assert is_parallel_pipeline("generative_editing_custom") is True
    assert is_parallel_pipeline("generative_t2i") is True
    assert is_parallel_pipeline("trellis") is True


def test_same_pool_names_for_compute():
    assert names_in_same_pool("face_swap") == {"face_swap", "face_recognition"}


def test_same_pool_names_for_dispatch():
    expected = {
        "generative_editing",
        "sharp",
        "generative_editing_custom",
        "generative_t2i",
        "trellis",
        "flux_opt_a10g",
        "flux_opt_h100",
        "flux_modal_mock",
        "flux_local_mock",
    }
    assert names_in_same_pool("generative_editing") == expected
    assert names_in_same_pool("sharp") == expected
    assert names_in_same_pool("generative_editing_custom") == expected
    assert names_in_same_pool("generative_t2i") == expected
    assert names_in_same_pool("trellis") == expected


def test_flux_opt_routes_to_dispatch_queue():
    assert get_routing_key("flux_opt_a10g") == rabbitmq_config.routing_dispatch
    assert get_routing_key("flux_opt_h100") == rabbitmq_config.routing_dispatch
    assert get_routing_key("flux_modal_mock") == rabbitmq_config.routing_dispatch
    assert get_routing_key("flux_local_mock") == rabbitmq_config.routing_dispatch


def test_flux_opt_is_parallel():
    assert is_parallel_pipeline("flux_opt_a10g") is True
    assert is_parallel_pipeline("flux_opt_h100") is True
    assert is_parallel_pipeline("flux_modal_mock") is True
    assert is_parallel_pipeline("flux_local_mock") is True
