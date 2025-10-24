import pytest
from pydantic import ValidationError

from services.compute.app.pipelines.schemas import (
    PipelineInput,
    RecastPipelineInput,
)


def test_pipeline_input_base():
    input_data = PipelineInput()
    assert input_data is not None


def test_recast_pipeline_input_valid():
    input_data = RecastPipelineInput(
        source_image_bucket="bucket1",
        source_image_key="image.jpg",
        template_image_bucket="bucket2",
        template_image_key="template.jpg",
    )

    assert input_data.source_image_bucket == "bucket1"
    assert input_data.source_image_key == "image.jpg"
    assert input_data.template_image_bucket == "bucket2"
    assert input_data.template_image_key == "template.jpg"


def test_recast_pipeline_input_missing_fields():
    with pytest.raises(ValidationError):
        RecastPipelineInput(
            source_image_bucket="bucket1",
        )


def test_recast_pipeline_input_extra_fields():
    input_data = RecastPipelineInput(
        source_image_bucket="bucket1",
        source_image_key="image.jpg",
        template_image_bucket="bucket2",
        template_image_key="template.jpg",
        extra_field="should be ignored",
    )

    assert not hasattr(input_data, "extra_field")
