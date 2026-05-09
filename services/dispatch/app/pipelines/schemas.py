from pydantic import BaseModel


class PipelineInput(BaseModel):
    pass


class GenerativeEditingPipelineInput(PipelineInput):
    """User-supplied photo + selected preset slug.

    Core resolves the preset's hidden prompt server-side from the slug —
    the dispatch worker never receives raw prompts from clients.
    """

    image_bucket: str
    image_key: str
    preset_slug: str
