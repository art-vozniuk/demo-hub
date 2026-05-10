"""Async dispatch pipelines. Each Pipeline is purely IO-bound — it
fetches inputs, calls a remote inference service, uploads the result,
and returns a structured payload identical in shape to compute pipelines.
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Any

from PIL import Image, ImageOps

from services.common.s3.client import S3Client

from .modal_client import invoke_generative_editing
from .schemas import GenerativeEditingPipelineInput

log = logging.getLogger(__name__)


class AsyncPipeline:
    async def run(self) -> dict[str, Any]:
        raise NotImplementedError


def _bake_exif_orientation(image_bytes: bytes) -> bytes:
    # Phones save JPEGs upright with an EXIF Orientation tag instead of
    # rotating pixels, and FLUX's PIL.Image.open downstream silently drops
    # that tag — so the model sees the photo sideways. Bake the rotation
    # into the pixels here, then re-encode. FLUX downscales to 1024 max
    # side anyway, so a single JPEG round-trip is invisible.
    with Image.open(io.BytesIO(image_bytes)) as img:
        oriented = ImageOps.exif_transpose(img)
        if oriented.mode != "RGB":
            oriented = oriented.convert("RGB")
        out = io.BytesIO()
        oriented.save(out, format="JPEG", quality=95)
        return out.getvalue()


class GenerativeEditingPipeline(AsyncPipeline):
    """User photo → FLUX.2 klein image-conditioned edit on Modal."""

    def __init__(
        self,
        s3: S3Client,
        pipeline_input: GenerativeEditingPipelineInput,
    ) -> None:
        self.s3 = s3
        self.pipeline_input = pipeline_input

    async def run(self) -> dict[str, Any]:
        image_bytes = await self.s3.download_file(
            s3_bucket=self.pipeline_input.image_bucket,
            s3_key=self.pipeline_input.image_key,
        )

        image_bytes = _bake_exif_orientation(image_bytes)

        payload = {
            "image_b64": base64.b64encode(image_bytes).decode("ascii"),
            "prompt": self.pipeline_input.prompt,
        }

        result = await invoke_generative_editing(payload)

        result_b64 = result.get("image_b64")
        if not result_b64:
            raise RuntimeError("Modal endpoint returned no image_b64 in response")

        result_bytes = base64.b64decode(result_b64)
        url = await self.s3.upload_file(
            data_bytes=result_bytes,
            s3_bucket=self.pipeline_input.image_bucket,
            s3_folder="generative_results",
            file_extension="png",
        )

        log.info(f"Dispatched generative_editing complete; uploaded result to {url}")
        return {"result_url": url}
