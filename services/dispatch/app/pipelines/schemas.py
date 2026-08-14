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


class TranscriberPipelineInput(PipelineInput):
    """User-supplied audio plus the knobs the transcript demo exposes.

    Every knob is optional: None means "let the Modal app apply its own
    default", so the allowed model/language sets live in one place
    (services/modal/transcriber/app.py) instead of being mirrored here.
    """

    audio_bucket: str
    audio_key: str
    model: str | None = None
    language: str | None = None
    num_speakers: int | None = None
    llm_cleanup: bool = False


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
    """Input for the optimised FLUX deployment. Same shape as
    generative_editing — the A10G vs H100 variant comes from the
    pipeline_name routing in core, not from this payload."""

    image_bucket: str
    image_key: str
    prompt: str
    num_inference_steps: int | None = None
    max_side: int | None = None
