"""User photo + free-form prompt → FLUX.2 klein image edit on Modal.

Same Modal app as generative_editing, just without preset resolution —
the user supplies the prompt directly. Dispatch forwards the S3 source
location and the prompt; Modal handles download, inference, upload.
"""

from __future__ import annotations

import logging
from typing import Any

from services.common.s3.client import S3Client

from .base import AsyncPipeline
from .modal_client import invoke_generative_editing_custom
from .schemas import GenerativeEditingCustomPipelineInput


log = logging.getLogger(__name__)


class GenerativeEditingCustomPipeline(AsyncPipeline):
    def __init__(
        self,
        s3: S3Client,
        pipeline_input: GenerativeEditingCustomPipelineInput,
    ) -> None:
        # s3 is plumbed in by the service factory but unused — Modal owns
        # both the download and the upload.
        self.s3 = s3
        self.pipeline_input = pipeline_input

    async def run(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "image_bucket": self.pipeline_input.image_bucket,
            "image_key": self.pipeline_input.image_key,
            "prompt": self.pipeline_input.prompt,
        }
        if self.pipeline_input.num_inference_steps is not None:
            payload["num_inference_steps"] = self.pipeline_input.num_inference_steps

        result = await invoke_generative_editing_custom(payload)

        result_url = result.get("result_url")
        if not result_url:
            raise RuntimeError(
                f"Modal endpoint returned no result_url; keys: {list(result.keys())}"
            )

        log.info(
            f"Dispatched generative_editing_custom complete; result at {result_url}"
        )
        return {"result_url": result_url}
