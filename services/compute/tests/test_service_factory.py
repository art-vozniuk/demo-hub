import pytest

from services.compute.app.pipelines.service import (
    create_service,
    FaceRecognitionService,
    FaceSwapService,
)
from services.compute.app.pipelines.schemas import (
    FaceRecognitionPipelineInput,
    FaceSwapPipelineInput,
)


def test_create_service_face_recognition_pipeline(mock_s3_client):
    service = create_service(
        pipeline_id="test-id",
        pipeline_name="face_recognition",
        pipeline_input={
            "image_bucket": "bucket1",
            "image_key": "image.jpg",
        },
        s3_client=mock_s3_client,
    )

    assert isinstance(service, FaceRecognitionService)
    assert service.id == "test-id"
    assert isinstance(service.pipeline_input, FaceRecognitionPipelineInput)


def test_create_service_face_swap_pipeline(mock_s3_client):
    service = create_service(
        pipeline_id="test-id",
        pipeline_name="face_swap",
        pipeline_input={
            "source_image_bucket": "bucket1",
            "source_image_key": "source.jpg",
            "template_image_bucket": "bucket2",
            "template_image_key": "template.jpg",
            "source_face_bbox": [1.0, 2.0, 3.0, 4.0],
            "target_face_bbox": [5.0, 6.0, 7.0, 8.0],
        },
        s3_client=mock_s3_client,
    )

    assert isinstance(service, FaceSwapService)
    assert service.id == "test-id"
    assert isinstance(service.pipeline_input, FaceSwapPipelineInput)
    assert service.pipeline_input.source_face_bbox == [1.0, 2.0, 3.0, 4.0]
    assert service.pipeline_input.target_face_bbox == [5.0, 6.0, 7.0, 8.0]


def test_create_service_face_swap_pipeline_without_bboxes(mock_s3_client):
    service = create_service(
        pipeline_id="test-id",
        pipeline_name="face_swap",
        pipeline_input={
            "source_image_bucket": "bucket1",
            "source_image_key": "source.jpg",
            "template_image_bucket": "bucket2",
            "template_image_key": "template.jpg",
        },
        s3_client=mock_s3_client,
    )

    assert isinstance(service, FaceSwapService)
    assert service.pipeline_input.source_face_bbox is None
    assert service.pipeline_input.target_face_bbox is None


def test_create_service_invalid_pipeline_name(mock_s3_client):
    with pytest.raises(ValueError, match="Invalid pipeline type"):
        create_service(
            pipeline_id="test-id",
            pipeline_name="nonexistent",
            pipeline_input={},
            s3_client=mock_s3_client,
        )


def test_create_service_invalid_face_swap_input(mock_s3_client):
    with pytest.raises(ValueError, match="Invalid input for face_swap"):
        create_service(
            pipeline_id="test-id",
            pipeline_name="face_swap",
            pipeline_input={"invalid": "data"},
            s3_client=mock_s3_client,
        )


def test_create_service_invalid_face_recognition_input(mock_s3_client):
    with pytest.raises(ValueError, match="Invalid input for face_recognition"):
        create_service(
            pipeline_id="test-id",
            pipeline_name="face_recognition",
            pipeline_input={"invalid": "data"},
            s3_client=mock_s3_client,
        )
