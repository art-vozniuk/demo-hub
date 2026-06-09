"""Dispatch-side wiring for the optimised FLUX deployment.

Two variants (A10G + H100 batched) live in services/modal/flux_opt/app.py
behind distinct submit/poll endpoint pairs. Pipeline_name from core's
routing picks the variant — payload shape is identical."""

from __future__ import annotations

import logging
from typing import Any

from services.common.s3.client import S3Client

from .base import AsyncPipeline
from .modal_client import invoke_flux_opt_a10g, invoke_flux_opt_h100
from .schemas import FluxOptPipelineInput

log = logging.getLogger(__name__)


def _to_payload(inp: FluxOptPipelineInput) -> dict[str, Any]:
    p: dict[str, Any] = {
        "image_bucket": inp.image_bucket,
        "image_key": inp.image_key,
        "prompt": inp.prompt,
    }
    if inp.num_inference_steps is not None:
        p["num_inference_steps"] = inp.num_inference_steps
    if inp.max_side is not None:
        p["max_side"] = inp.max_side
    return p


class FluxOptA10GPipeline(AsyncPipeline):
    def __init__(self, s3: S3Client, pipeline_input: FluxOptPipelineInput) -> None:
        self.s3 = s3
        self.pipeline_input = pipeline_input

    async def run(self) -> dict[str, Any]:
        return await invoke_flux_opt_a10g(_to_payload(self.pipeline_input))


class FluxOptH100Pipeline(AsyncPipeline):
    def __init__(self, s3: S3Client, pipeline_input: FluxOptPipelineInput) -> None:
        self.s3 = s3
        self.pipeline_input = pipeline_input

    async def run(self) -> dict[str, Any]:
        return await invoke_flux_opt_h100(_to_payload(self.pipeline_input))
