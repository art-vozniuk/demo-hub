import pytest

from services.compute.app.pipelines.service import (
    create_service,
    RecastService,
)
from services.compute.app.pipelines.schemas import RecastPipelineInput


def test_create_service_recast_pipeline(mock_s3_client):
    service = create_service(
        pipeline_id="test-id",
        pipeline_name="recast",
        pipeline_input={
            "source_image_bucket": "bucket1",
            "source_image_key": "source.jpg",
            "template_image_bucket": "bucket2",
            "template_image_key": "template.jpg",
        },
        s3_client=mock_s3_client,
    )

    assert isinstance(service, RecastService)
    assert service.id == "test-id"
    assert isinstance(service.pipeline_input, RecastPipelineInput)


def test_create_service_invalid_pipeline_name(mock_s3_client):
    with pytest.raises(ValueError, match="Invalid pipeline type"):
        create_service(
            pipeline_id="test-id",
            pipeline_name="nonexistent",
            pipeline_input={},
            s3_client=mock_s3_client,
        )


def test_create_service_invalid_input(mock_s3_client):
    with pytest.raises(ValueError, match="Invalid input for recast"):
        create_service(
            pipeline_id="test-id",
            pipeline_name="recast",
            pipeline_input={"invalid": "data"},
            s3_client=mock_s3_client,
        )
