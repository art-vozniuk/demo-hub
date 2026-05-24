"""Free-form prompt → image via FLUX.1 [schnell] on a dedicated Modal app.

Distinct from generative_editing_custom (which is image-conditioned edits
on FLUX.2 klein). Carries the rendered image's S3 location back so a
caller can pipe it straight into another pipeline (e.g. sharp) without
re-uploading.
"""

from __future__ import annotations

import logging
from typing import Any

from services.common.s3.client import S3Client

from .base import AsyncPipeline
from .modal_client import invoke_generative_t2i
from .schemas import GenerativeT2IPipelineInput


log = logging.getLogger(__name__)


class GenerativeT2IPipeline(AsyncPipeline):
    def __init__(
        self,
        s3: S3Client,
        pipeline_input: GenerativeT2IPipelineInput,
    ) -> None:
        # Modal owns upload + download; s3 plumbed in for parity only.
        self.s3 = s3
        self.pipeline_input = pipeline_input

    async def run(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "prompt": self.pipeline_input.prompt,
            "output_bucket": self.pipeline_input.output_bucket,
        }
        # Pass through every optional knob the user touched; Modal applies
        # its own defaults for anything we leave unset.
        for key in (
            "seed",
            "num_inference_steps",
            "width",
            "height",
            "init_image_bucket",
            "init_image_key",
            "strength",
        ):
            value = getattr(self.pipeline_input, key)
            if value is not None:
                payload[key] = value

        result = await invoke_generative_t2i(payload)

        result_url = result.get("result_url")
        image_bucket = result.get("image_bucket")
        image_key = result.get("image_key")
        if not result_url or not image_bucket or not image_key:
            raise RuntimeError(
                f"Modal endpoint returned incomplete result; keys: {list(result.keys())}"
            )

        log.info(f"Dispatched generative_t2i complete; result at {result_url}")
        return {
            "result_url": result_url,
            "image_bucket": image_bucket,
            "image_key": image_key,
            "width": result.get("width"),
            "height": result.get("height"),
            "seed": result.get("seed"),
        }
