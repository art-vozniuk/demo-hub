"""Async dispatch pipelines. Each Pipeline is purely IO-bound — it
fetches inputs, calls a remote inference service, uploads the result,
and returns a structured payload identical in shape to compute pipelines.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from services.common.s3.client import S3Client
from services.dispatch.app.config import config as dispatch_config

from .modal_client import invoke_generative_editing
from .schemas import GenerativeEditingPipelineInput

log = logging.getLogger(__name__)


class AsyncPipeline:
    async def run(self) -> dict[str, Any]:
        raise NotImplementedError


class GenerativeEditingPipeline(AsyncPipeline):
    """User photo → FLUX.2 klein image-conditioned edit on Modal.

    The prompt template is resolved from the preset slug via core's
    internal HTTP endpoint, so the user-facing client never transmits
    raw prompts.
    """

    def __init__(
        self,
        s3: S3Client,
        pipeline_input: GenerativeEditingPipelineInput,
        core_internal_url: str | None = None,
    ) -> None:
        self.s3 = s3
        self.pipeline_input = pipeline_input
        self.core_internal_url = (
            core_internal_url or dispatch_config.CORE_INTERNAL_URL
        ).rstrip("/")

    async def _resolve_prompt(self) -> str:
        url = (
            f"{self.core_internal_url}/api/v1/generative/internal/presets/"
            f"{self.pipeline_input.preset_slug}"
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code == 404:
                raise RuntimeError(
                    f"Preset {self.pipeline_input.preset_slug!r} not found"
                )
            resp.raise_for_status()
            data = resp.json()
        prompt = data.get("prompt")
        if not prompt:
            raise RuntimeError(
                f"Preset {self.pipeline_input.preset_slug!r} has empty prompt"
            )
        return prompt

    async def run(self) -> dict[str, Any]:
        image_bytes = await self.s3.download_file(
            s3_bucket=self.pipeline_input.image_bucket,
            s3_key=self.pipeline_input.image_key,
        )
        prompt = await self._resolve_prompt()

        payload = {
            "image_b64": base64.b64encode(image_bytes).decode("ascii"),
            "prompt": prompt,
            "preset_slug": self.pipeline_input.preset_slug,
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
