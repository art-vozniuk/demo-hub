"""Bench dispatch path — flux_opt variants (A10G + H100) and the two
mocks. Each pipeline forwards to a different Modal endpoint pair, with
the run_id stamped into the payload so the Modal-side push metrics
inherit the same tag as the dispatch-side ones."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from services.common.s3.client import S3Client

from .base import AsyncPipeline
from .modal_client import (
    invoke_flux_mock,
    invoke_flux_opt_a10g,
    invoke_flux_opt_h100,
)
from .schemas import FluxMockPipelineInput, FluxOptPipelineInput

log = logging.getLogger(__name__)


def _to_payload(inp: FluxOptPipelineInput) -> dict[str, Any]:
    p: dict[str, Any] = {
        "image_bucket": inp.image_bucket,
        "image_key": inp.image_key,
        "prompt": inp.prompt,
        "run_id": inp.run_id,
    }
    if inp.num_inference_steps is not None:
        p["num_inference_steps"] = inp.num_inference_steps
    if inp.max_side is not None:
        p["max_side"] = inp.max_side
    return p


class FluxOptA10GPipeline(AsyncPipeline):
    def __init__(
        self, s3: S3Client, pipeline_input: FluxOptPipelineInput
    ) -> None:
        self.s3 = s3
        self.pipeline_input = pipeline_input

    async def run(self) -> dict[str, Any]:
        return await invoke_flux_opt_a10g(_to_payload(self.pipeline_input))


class FluxOptH100Pipeline(AsyncPipeline):
    def __init__(
        self, s3: S3Client, pipeline_input: FluxOptPipelineInput
    ) -> None:
        self.s3 = s3
        self.pipeline_input = pipeline_input

    async def run(self) -> dict[str, Any]:
        return await invoke_flux_opt_h100(_to_payload(self.pipeline_input))


class FluxModalMockPipeline(AsyncPipeline):
    def __init__(
        self, s3: S3Client, pipeline_input: FluxMockPipelineInput
    ) -> None:
        self.s3 = s3
        self.pipeline_input = pipeline_input

    async def run(self) -> dict[str, Any]:
        return await invoke_flux_mock(
            {"prompt": self.pipeline_input.prompt, "run_id": self.pipeline_input.run_id}
        )


class FluxLocalMockPipeline(AsyncPipeline):
    """Never touches Modal — sleeps locally and returns a stub URL.
    Use this for $0 UI/coordinator iteration."""

    def __init__(
        self, s3: S3Client, pipeline_input: FluxMockPipelineInput
    ) -> None:
        self.s3 = s3
        self.pipeline_input = pipeline_input

    async def run(self) -> dict[str, Any]:
        delay = random.uniform(0.5, 2.0)
        await asyncio.sleep(delay)
        return {
            "result_url": f"stub://flux-local-mock/{self.pipeline_input.run_id}",
            "width": 1024,
            "height": 1024,
        }
