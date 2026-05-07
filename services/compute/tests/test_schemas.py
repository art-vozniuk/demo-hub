import pytest
from pydantic import ValidationError

from services.compute.app.pipelines.schemas import (
    PipelineInput,
    FaceRecognitionPipelineInput,
    FaceSwapPipelineInput,
)


def test_pipeline_input_base():
    input_data = PipelineInput()
    assert input_data is not None


def test_face_recognition_pipeline_input_valid():
    input_data = FaceRecognitionPipelineInput(
        image_bucket="bucket1",
        image_key="image.jpg",
    )

    assert input_data.image_bucket == "bucket1"
    assert input_data.image_key == "image.jpg"


def test_face_recognition_pipeline_input_missing_fields():
    with pytest.raises(ValidationError):
        FaceRecognitionPipelineInput(image_bucket="bucket1")


def test_face_swap_pipeline_input_valid():
    input_data = FaceSwapPipelineInput(
        source_image_bucket="bucket1",
        source_image_key="image.jpg",
        template_image_bucket="bucket2",
        template_image_key="template.jpg",
    )

    assert input_data.source_image_bucket == "bucket1"
    assert input_data.source_image_key == "image.jpg"
    assert input_data.template_image_bucket == "bucket2"
    assert input_data.template_image_key == "template.jpg"
    assert input_data.source_face_bbox is None
    assert input_data.target_face_bbox is None


def test_face_swap_pipeline_input_with_bboxes():
    input_data = FaceSwapPipelineInput(
        source_image_bucket="bucket1",
        source_image_key="image.jpg",
        template_image_bucket="bucket2",
        template_image_key="template.jpg",
        source_face_bbox=[10.0, 20.0, 100.0, 200.0],
        target_face_bbox=[5.5, 6.5, 50.0, 80.0],
    )

    assert input_data.source_face_bbox == [10.0, 20.0, 100.0, 200.0]
    assert input_data.target_face_bbox == [5.5, 6.5, 50.0, 80.0]


def test_face_swap_pipeline_input_missing_fields():
    with pytest.raises(ValidationError):
        FaceSwapPipelineInput(source_image_bucket="bucket1")


def test_face_swap_pipeline_input_extra_fields():
    input_data = FaceSwapPipelineInput(
        source_image_bucket="bucket1",
        source_image_key="image.jpg",
        template_image_bucket="bucket2",
        template_image_key="template.jpg",
        extra_field="should be ignored",
    )

    assert not hasattr(input_data, "extra_field")
