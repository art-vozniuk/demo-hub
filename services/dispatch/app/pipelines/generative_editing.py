"""User photo → FLUX.2 klein image-conditioned edit on Modal.

Dispatch only forwards the S3 location of the source photo to Modal;
Modal downloads, bakes EXIF, runs inference, and uploads the result
back to S3 itself. Dispatch never sees the image bytes.
"""

from __future__ import annotations

import logging
from typing import Any

from services.common.s3.client import S3Client

from .base import AsyncPipeline
from .modal_client import invoke_generative_editing
from .schemas import GenerativeEditingPipelineInput


log = logging.getLogger(__name__)


class GenerativeEditingPipeline(AsyncPipeline):
    def __init__(
        self,
        s3: S3Client,
        pipeline_input: GenerativeEditingPipelineInput,
    ) -> None:
        # s3 is plumbed in by the service factory but unused — Modal owns
        # both the download and the upload now.
        self.s3 = s3
        self.pipeline_input = pipeline_input

    async def run(self) -> dict[str, Any]:
        payload = {
            "image_bucket": self.pipeline_input.image_bucket,
            "image_key": self.pipeline_input.image_key,
            "prompt": self.pipeline_input.prompt,
        }

        result = await invoke_generative_editing(payload)

        result_url = result.get("result_url")
        if not result_url:
            raise RuntimeError(
                f"Modal endpoint returned no result_url; keys: {list(result.keys())}"
            )

        log.info(f"Dispatched generative_editing complete; result at {result_url}")
        return {"result_url": result_url}
