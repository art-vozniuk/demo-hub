"""Pipeline registry mirror of services/compute/app/pipelines/service.py
— same factory shape, but async and without an inference lock. IO-bound
work parallelises freely; the only ceiling is the consumer's
max_concurrent_tasks semaphore.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic_core._pydantic_core import ValidationError

from services.common.s3.client import S3Client

from .base import AsyncPipeline
from .generative_editing import GenerativeEditingPipeline
from .generative_editing_custom import GenerativeEditingCustomPipeline
from .generative_t2i import GenerativeT2IPipeline
from .schemas import (
    GenerativeEditingCustomPipelineInput,
    GenerativeEditingPipelineInput,
    GenerativeT2IPipelineInput,
    PipelineInput,
    SharpPipelineInput,
    TrellisPipelineInput,
)
from .sharp import SharpPipeline
from .trellis import TrellisPipeline

log = logging.getLogger(__name__)


class Service:
    def __init__(
        self,
        id: str,
        s3: S3Client,
        pipeline_input: PipelineInput,
    ) -> None:
        self.id = id
        self.s3 = s3
        self.pipeline_input = pipeline_input
        self.last_inference_ms: float = 0.0

    @staticmethod
    async def initialize(s3: S3Client) -> None:
        return None

    async def prepare_pipeline(self) -> AsyncPipeline:
        raise NotImplementedError

    async def run(self) -> dict[str, Any]:
        pipeline = await self.prepare_pipeline()
        t0 = time.perf_counter()
        result = await pipeline.run()
        self.last_inference_ms = (time.perf_counter() - t0) * 1000.0
        return result


class GenerativeEditingService(Service):
    async def prepare_pipeline(self) -> AsyncPipeline:
        if not isinstance(self.pipeline_input, GenerativeEditingPipelineInput):
            raise ValueError("Invalid pipeline input for GenerativeEditingService")
        return GenerativeEditingPipeline(
            s3=self.s3,
            pipeline_input=self.pipeline_input,
        )


class SharpService(Service):
    async def prepare_pipeline(self) -> AsyncPipeline:
        if not isinstance(self.pipeline_input, SharpPipelineInput):
            raise ValueError("Invalid pipeline input for SharpService")
        return SharpPipeline(
            s3=self.s3,
            pipeline_input=self.pipeline_input,
        )


class TrellisService(Service):
    async def prepare_pipeline(self) -> AsyncPipeline:
        if not isinstance(self.pipeline_input, TrellisPipelineInput):
            raise ValueError("Invalid pipeline input for TrellisService")
        return TrellisPipeline(
            s3=self.s3,
            pipeline_input=self.pipeline_input,
        )


class GenerativeEditingCustomService(Service):
    async def prepare_pipeline(self) -> AsyncPipeline:
        if not isinstance(self.pipeline_input, GenerativeEditingCustomPipelineInput):
            raise ValueError(
                "Invalid pipeline input for GenerativeEditingCustomService"
            )
        return GenerativeEditingCustomPipeline(
            s3=self.s3,
            pipeline_input=self.pipeline_input,
        )


class GenerativeT2IService(Service):
    async def prepare_pipeline(self) -> AsyncPipeline:
        if not isinstance(self.pipeline_input, GenerativeT2IPipelineInput):
            raise ValueError("Invalid pipeline input for GenerativeT2IService")
        return GenerativeT2IPipeline(
            s3=self.s3,
            pipeline_input=self.pipeline_input,
        )


class PipelineType:
    def __init__(
        self,
        service_type: type[Service],
        input_type: type[PipelineInput],
        estimated_time_ms: int,
    ) -> None:
        self.service_type = service_type
        self.input_type = input_type
        # Mutated in place by heartbeat.record_success after each run, so
        # the next heartbeat tick advertises the latest wall time.
        self.estimated_time_ms = estimated_time_ms


pipeline_templates: dict[str, PipelineType] = {
    "generative_editing": PipelineType(
        service_type=GenerativeEditingService,
        input_type=GenerativeEditingPipelineInput,
        estimated_time_ms=30_000,
    ),
    "generative_editing_custom": PipelineType(
        service_type=GenerativeEditingCustomService,
        input_type=GenerativeEditingCustomPipelineInput,
        # Same Modal app as generative_editing; mirror its initial ETA.
        estimated_time_ms=30_000,
    ),
    "sharp": PipelineType(
        service_type=SharpService,
        input_type=SharpPipelineInput,
        estimated_time_ms=8_000,
    ),
    "trellis": PipelineType(
        service_type=TrellisService,
        input_type=TrellisPipelineInput,
        estimated_time_ms=25_000,
    ),
    "generative_t2i": PipelineType(
        service_type=GenerativeT2IService,
        input_type=GenerativeT2IPipelineInput,
        estimated_time_ms=30_000,
    ),
}


def create_service(
    pipeline_id: str,
    pipeline_name: str,
    pipeline_input: dict,
    s3_client: S3Client,
) -> Service:
    template = pipeline_templates.get(pipeline_name)
    if not template:
        raise ValueError(f"Invalid pipeline type: {pipeline_name}")

    try:
        validated_input = template.input_type.model_validate(pipeline_input)
    except ValidationError as e:
        raise ValueError(f"Invalid input for {pipeline_name}: {e}")

    return template.service_type(
        id=pipeline_id,
        s3=s3_client,
        pipeline_input=validated_input,
    )
