"""User photo → FLUX.2 klein image-conditioned edit on Modal."""

from __future__ import annotations

import base64
import logging
from typing import Any

from services.common.s3.client import S3Client

from .base import AsyncPipeline, bake_exif_orientation
from .modal_client import invoke_generative_editing
from .schemas import GenerativeEditingPipelineInput


log = logging.getLogger(__name__)


class GenerativeEditingPipeline(AsyncPipeline):
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

        image_bytes = bake_exif_orientation(image_bytes)

        payload = {
            "image_b64": base64.b64encode(image_bytes).decode("ascii"),
            "prompt": self.pipeline_input.prompt,
            "image_bucket": self.pipeline_input.image_bucket,
        }

        result = await invoke_generative_editing(payload)

        result_url = result.get("result_url")
        if not result_url:
            raise RuntimeError(
                f"Modal endpoint returned no result_url; keys: {list(result.keys())}"
            )

        log.info(f"Dispatched generative_editing complete; result at {result_url}")
        return {"result_url": result_url}
