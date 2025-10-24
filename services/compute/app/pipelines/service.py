import asyncio
import logging
import time

from pydantic_core._pydantic_core import ValidationError

from services.common.s3.client import S3Client
from services.compute.app.pipelines.pipelines import (
    Pipeline,
    RecastPipeline,
)
from services.compute.app.pipelines.schemas import PipelineInput, RecastPipelineInput

log = logging.getLogger(__name__)

_recast_template_cache: dict[str, bytes] = {}
_inference_lock = asyncio.Lock()


class Service:
    def __init__(self, id: str, s3: S3Client, pipeline_input: PipelineInput):
        self.id = id
        self.s3 = s3
        self.pipeline_input = pipeline_input

    @staticmethod
    async def initialize(s3: S3Client):
        pass

    @staticmethod
    async def download_model(
        s3: S3Client, relative_path: str, check_exists: bool = False
    ) -> str:
        import os

        absolute_path = os.path.abspath(relative_path)
        if check_exists and os.path.exists(absolute_path):
            return absolute_path

        os.makedirs(os.path.dirname(absolute_path), exist_ok=True)

        name = os.path.basename(relative_path)
        s3_key = f"models/{name}"
        await s3.download_file_to_disc(
            s3_bucket="media", s3_key=s3_key, path=absolute_path
        )

        return absolute_path

    async def prepare_pipeline(self) -> Pipeline:
        raise NotImplementedError

    async def post_pipeline(self, results: dict) -> dict:
        raise NotImplementedError

    async def run(self) -> dict:
        t1 = time.perf_counter()
        log.info(f"Starting pipeline {self.id}")
        pipeline = await self.prepare_pipeline()
        log.info(
            f"Service.run prepare_pipeline took {(time.perf_counter() - t1) * 1000:.1f}ms"
        )

        t1 = time.perf_counter()
        async with _inference_lock:
            wait_time = (time.perf_counter() - t1) * 1000
            log.info(f"[{self.id}] Waited {wait_time:.1f}ms for GPU lock")

            t1 = time.perf_counter()
            results = await asyncio.to_thread(lambda: pipeline.run())
            log.info(
                f"Service.run pipeline.run took {(time.perf_counter() - t1) * 1000:.1f}ms"
            )

        t1 = time.perf_counter()
        output = await self.post_pipeline(results)
        log.info(
            f"Service.run post_pipeline took {(time.perf_counter() - t1) * 1000:.1f}ms"
        )
        log.info(f"Completed pipeline {self.id}")
        return output


class RecastService(Service):
    def __init__(self, id: str, s3: S3Client, pipeline_input: PipelineInput):
        Service.__init__(self, id, s3, pipeline_input)

    @staticmethod
    async def initialize(s3: S3Client):
        await Service.download_model(
            s3,
            relative_path="../external/face_swap/models/insightface/inswapper_128.onnx",
            check_exists=True,
        )

    async def prepare_pipeline(self) -> Pipeline:
        if not isinstance(self.pipeline_input, RecastPipelineInput):
            raise ValueError("Invalid pipeline input for RecastService")

        key = f"{self.pipeline_input.template_image_bucket}/{self.pipeline_input.template_image_key}"
        if key in _recast_template_cache:
            log.info(f"Using cached template image for key: {key}")
            target_image = _recast_template_cache[key]
            source_image = await self.s3.download_file(
                s3_bucket=self.pipeline_input.source_image_bucket,
                s3_key=self.pipeline_input.source_image_key,
            )
            return RecastPipeline(source_image, target_image)

        source_image_task = self.s3.download_file(
            s3_bucket=self.pipeline_input.source_image_bucket,
            s3_key=self.pipeline_input.source_image_key,
        )
        target_image_task = self.s3.download_file(
            s3_bucket=self.pipeline_input.template_image_bucket,
            s3_key=self.pipeline_input.template_image_key,
        )

        source_image, target_image = await asyncio.gather(
            source_image_task, target_image_task
        )

        _recast_template_cache[key] = target_image

        return RecastPipeline(source_image, target_image)

    async def post_pipeline(self, results: dict) -> dict:
        file_extension = self.pipeline_input.source_image_key.split(".")[-1].lower()
        url = await self.s3.upload_file(
            data_bytes=results["image"],
            s3_bucket=self.pipeline_input.source_image_bucket,
            s3_folder="recast_results",
            file_extension=file_extension,
        )
        return {"url": url}


class PipelineType:
    def __init__(
        self,
        service_type: type[Service],
        pipeline_type: type[Pipeline],
        input_type: type[PipelineInput],
    ):
        self.service_type = service_type
        self.pipeline_type = pipeline_type
        self.input_type = input_type

    service_type: type[Service]
    pipeline_type: type[Pipeline]
    input_type: type[PipelineInput]


pipeline_templates = {
    "recast": PipelineType(
        service_type=RecastService,
        pipeline_type=RecastPipeline,
        input_type=RecastPipelineInput,
    ),
}


def create_service(
    pipeline_id: str, pipeline_name: str, pipeline_input: dict, s3_client: S3Client
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
