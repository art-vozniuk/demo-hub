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


class SharpPipelineInput(PipelineInput):
    """User-supplied photo. SHARP needs nothing else — single forward pass,
    no preset, no prompt, no params. We forward only the S3 location of
    the uploaded image.
    """

    image_bucket: str
    image_key: str


class TrellisPipelineInput(PipelineInput):
    """User-supplied image plus optional sampler-steps knob driving the
    quality/speed/cost tradeoff. None falls back to the Modal default (8).
    """

    image_bucket: str
    image_key: str
    steps: int | None = None


class GenerativeEditingCustomPipelineInput(PipelineInput):
    """User-supplied photo + free-form prompt. Same Modal app as
    generative_editing, but bypasses preset resolution — the user types
    the prompt directly. `num_inference_steps` is exposed as a quality
    knob; None falls back to the Modal default (4).
    """

    image_bucket: str
    image_key: str
    prompt: str
    num_inference_steps: int | None = None


class GenerativeT2IPipelineInput(PipelineInput):
    prompt: str
    output_bucket: str
    seed: int | None = None
    num_inference_steps: int | None = None
    width: int | None = None
    height: int | None = None


class FluxOptPipelineInput(PipelineInput):
    """Same as generative editing, plus a run_id tag so the bench
    coordinator can aggregate metrics per experiment. Both A10G and
    H100 variants share this shape — the variant comes from the
    pipeline_name routing."""

    image_bucket: str
    image_key: str
    prompt: str
    run_id: str
    num_inference_steps: int | None = None
    max_side: int | None = None


class FluxMockPipelineInput(PipelineInput):
    """MOCK_LOCAL and MOCK_MODAL share this — the image key may be a
    stub since neither tier touches S3 in a way that matters."""

    image_bucket: str = ""
    image_key: str = ""
    prompt: str = ""
    run_id: str
