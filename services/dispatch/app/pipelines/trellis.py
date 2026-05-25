"""Generated image → Microsoft TRELLIS.2 textured GLB mesh on Modal.

Dispatch only forwards the S3 location of the source image to Modal;
Modal downloads it, runs the image→3D pipeline, exports the .glb, and
uploads it back to S3 itself. Dispatch never sees the bytes — it
forwards the result URL. Mirrors sharp.py one-for-one.
"""

from __future__ import annotations

import logging
from typing import Any

from services.common.s3.client import S3Client

from .base import AsyncPipeline
from .modal_client import invoke_trellis
from .schemas import TrellisPipelineInput


log = logging.getLogger(__name__)


class TrellisPipeline(AsyncPipeline):
    def __init__(
        self,
        s3: S3Client,
        pipeline_input: TrellisPipelineInput,
    ) -> None:
        # s3 is plumbed in by the service factory but unused — Modal owns
        # both the download and the upload now.
        self.s3 = s3
        self.pipeline_input = pipeline_input

    async def run(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "image_bucket": self.pipeline_input.image_bucket,
            "image_key": self.pipeline_input.image_key,
        }
        if self.pipeline_input.steps is not None:
            payload["steps"] = self.pipeline_input.steps

        result = await invoke_trellis(payload)

        result_url = result.get("result_url")
        if not result_url:
            raise RuntimeError(
                f"Modal TRELLIS endpoint returned no result_url; payload keys: "
                f"{list(result.keys())}"
            )

        log.info(f"Dispatched trellis complete; glb at {result_url}")
        return {"result_url": result_url}
