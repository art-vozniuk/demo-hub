import pytest

from services.dispatch.app.pipelines.service import (
    create_service,
    GenerativeEditingCustomService,
    GenerativeEditingService,
    SharpService,
)
from services.dispatch.app.pipelines.schemas import (
    GenerativeEditingCustomPipelineInput,
    GenerativeEditingPipelineInput,
    SharpPipelineInput,
)


def test_create_service_generative_editing(mock_s3_client):
    svc = create_service(
        pipeline_id="abc",
        pipeline_name="generative_editing",
        pipeline_input={
            "image_bucket": "media",
            "image_key": "user/foo.jpg",
            "preset_slug": "neo-tokyo",
            "prompt": "cinematic still",
        },
        s3_client=mock_s3_client,
    )

    assert isinstance(svc, GenerativeEditingService)
    assert svc.id == "abc"
    assert isinstance(svc.pipeline_input, GenerativeEditingPipelineInput)
    assert svc.pipeline_input.preset_slug == "neo-tokyo"
    assert svc.pipeline_input.prompt == "cinematic still"


def test_create_service_unknown_pipeline(mock_s3_client):
    with pytest.raises(ValueError, match="Invalid pipeline type"):
        create_service(
            pipeline_id="abc",
            pipeline_name="not_a_real_pipeline",
            pipeline_input={},
            s3_client=mock_s3_client,
        )


def test_create_service_invalid_input(mock_s3_client):
    with pytest.raises(ValueError, match="Invalid input for generative_editing"):
        create_service(
            pipeline_id="abc",
            pipeline_name="generative_editing",
            pipeline_input={"image_bucket": "media"},
            s3_client=mock_s3_client,
        )


def test_create_service_sharp(mock_s3_client):
    svc = create_service(
        pipeline_id="xyz",
        pipeline_name="sharp",
        pipeline_input={
            "image_bucket": "media",
            "image_key": "user/photo.jpg",
        },
        s3_client=mock_s3_client,
    )

    assert isinstance(svc, SharpService)
    assert svc.id == "xyz"
    assert isinstance(svc.pipeline_input, SharpPipelineInput)
    assert svc.pipeline_input.image_bucket == "media"
    assert svc.pipeline_input.image_key == "user/photo.jpg"


def test_create_service_sharp_invalid_input(mock_s3_client):
    with pytest.raises(ValueError, match="Invalid input for sharp"):
        create_service(
            pipeline_id="xyz",
            pipeline_name="sharp",
            pipeline_input={"image_bucket": "media"},  # missing image_key
            s3_client=mock_s3_client,
        )


def test_create_service_generative_editing_custom(mock_s3_client):
    svc = create_service(
        pipeline_id="gec",
        pipeline_name="generative_editing_custom",
        pipeline_input={
            "image_bucket": "media",
            "image_key": "user/photo.jpg",
            "prompt": "cinematic portrait, golden hour",
            "num_inference_steps": 8,
        },
        s3_client=mock_s3_client,
    )

    assert isinstance(svc, GenerativeEditingCustomService)
    assert svc.id == "gec"
    assert isinstance(svc.pipeline_input, GenerativeEditingCustomPipelineInput)
    assert svc.pipeline_input.prompt == "cinematic portrait, golden hour"
    assert svc.pipeline_input.num_inference_steps == 8


def test_create_service_generative_editing_custom_steps_optional(mock_s3_client):
    svc = create_service(
        pipeline_id="gec",
        pipeline_name="generative_editing_custom",
        pipeline_input={
            "image_bucket": "media",
            "image_key": "user/photo.jpg",
            "prompt": "ok",
        },
        s3_client=mock_s3_client,
    )

    assert isinstance(svc, GenerativeEditingCustomService)
    assert svc.pipeline_input.num_inference_steps is None


def test_create_service_generative_editing_custom_invalid_input(mock_s3_client):
    with pytest.raises(ValueError, match="Invalid input for generative_editing_custom"):
        create_service(
            pipeline_id="gec",
            pipeline_name="generative_editing_custom",
            pipeline_input={"image_bucket": "media"},  # missing image_key + prompt
            s3_client=mock_s3_client,
        )
