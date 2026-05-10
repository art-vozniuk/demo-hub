from pydantic import BaseModel


class PipelineInput(BaseModel):
    pass


class GenerativeEditingPipelineInput(PipelineInput):
    """User-supplied photo + prompt resolved by core at enqueue time.

    `preset_slug` is forwarded by core for traceability/logging; the
    dispatch worker only needs `prompt` to drive the Modal call.
    """

    image_bucket: str
    image_key: str
    preset_slug: str
    prompt: str
