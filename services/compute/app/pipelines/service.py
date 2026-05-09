import asyncio
import logging
import time

from pydantic_core._pydantic_core import ValidationError

from services.common.s3.client import S3Client
from services.compute.app.pipelines.pipelines import (
    Pipeline,
    FaceRecognitionPipeline,
    FaceSwapPipeline,
)
from services.compute.app.pipelines.schemas import (
    PipelineInput,
    FaceRecognitionPipelineInput,
    FaceSwapPipelineInput,
)

log = logging.getLogger(__name__)

_inference_lock = asyncio.Lock()


class Service:
    def __init__(self, id: str, s3: S3Client, pipeline_input: PipelineInput):
        self.id = id
        self.s3 = s3
        self.pipeline_input = pipeline_input
        self.last_inference_ms: float = 0.0

    @staticmethod
    async def initialize(s3: S3Client):
        pass

    @staticmethod
    async def download_model(
        s3: S3Client,
        relative_path: str,
        check_exists: bool = False,
    ) -> str:
        # Downloads a model into the container FS. Writes to a `.partial`
        # sibling and only atomically renames on full success, so a network
        # blip / OOM / restart mid-stream cannot leave a corrupted file at
        # the final path that future starts would reuse via check_exists=True.
        # Verifies Content-Length when the server provides it; mismatches
        # abort the download and clean up the partial.
        import os
        import aiohttp
        from services.compute.app.config import config

        absolute_path = os.path.abspath(relative_path)
        if check_exists and os.path.exists(absolute_path):
            return absolute_path

        os.makedirs(os.path.dirname(absolute_path), exist_ok=True)

        name = os.path.basename(relative_path)
        url = f"{config.MODELS_BASE_URL}/{name}"
        partial_path = absolute_path + ".partial"

        # Stale partial from a previous failed run — nuke it before retrying.
        if os.path.exists(partial_path):
            log.warning(f"Removing stale partial download: {partial_path}")
            os.remove(partial_path)

        log.info(f"Downloading model: {url}")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    expected_size = resp.content_length  # may be None
                    written = 0
                    with open(partial_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(8 * 1024 * 1024):
                            f.write(chunk)
                            written += len(chunk)

            if expected_size is not None and written != expected_size:
                raise IOError(
                    f"Download size mismatch for {name}: "
                    f"got {written} bytes, expected {expected_size}"
                )

            os.replace(partial_path, absolute_path)
            log.info(f"Downloaded {name} to {absolute_path} ({written} bytes)")
        except BaseException:
            # Best-effort cleanup so check_exists doesn't latch onto a half-file
            # on the next start. BaseException catches CancelledError too.
            if os.path.exists(partial_path):
                try:
                    os.remove(partial_path)
                except OSError:
                    pass
            raise

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
            self.last_inference_ms = (time.perf_counter() - t1) * 1000
            log.info(
                f"Service.run pipeline.run took {self.last_inference_ms:.1f}ms"
            )

        t1 = time.perf_counter()
        output = await self.post_pipeline(results)
        log.info(
            f"Service.run post_pipeline took {(time.perf_counter() - t1) * 1000:.1f}ms"
        )
        log.info(f"Completed pipeline {self.id}")
        return output


class FaceRecognitionService(Service):
    @staticmethod
    async def initialize(s3: S3Client):
        # Face detection uses the buffalo_l InsightFace bundle, which the
        # underlying `analyze_faces` lazily downloads on first call. No
        # model warmup needed here.
        pass

    async def prepare_pipeline(self) -> Pipeline:
        if not isinstance(self.pipeline_input, FaceRecognitionPipelineInput):
            raise ValueError("Invalid pipeline input for FaceRecognitionService")

        image = await self.s3.download_file(
            s3_bucket=self.pipeline_input.image_bucket,
            s3_key=self.pipeline_input.image_key,
        )
        return FaceRecognitionPipeline(image)

    async def post_pipeline(self, results: dict) -> dict:
        return results["payload"]


class FaceSwapService(Service):
    @staticmethod
    async def initialize(s3: S3Client):
        await Service.download_model(
            s3,
            relative_path="../external/face_swap/models/insightface/inswapper_128.onnx",
            check_exists=True,
        )

    async def prepare_pipeline(self) -> Pipeline:
        if not isinstance(self.pipeline_input, FaceSwapPipelineInput):
            raise ValueError("Invalid pipeline input for FaceSwapService")

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

        return FaceSwapPipeline(
            source_image,
            target_image,
            source_face_bbox=self.pipeline_input.source_face_bbox,
            target_face_bbox=self.pipeline_input.target_face_bbox,
        )

    async def post_pipeline(self, results: dict) -> dict:
        file_extension = self.pipeline_input.source_image_key.split(".")[-1].lower()
        url = await self.s3.upload_file(
            data_bytes=results["image"],
            s3_bucket=self.pipeline_input.source_image_bucket,
            s3_folder="recast_results",
            file_extension=file_extension,
        )
        return {"result_url": url}


class PipelineType:
    def __init__(
        self,
        service_type: type[Service],
        pipeline_type: type[Pipeline],
        input_type: type[PipelineInput],
        estimated_time_ms: int,
    ):
        self.service_type = service_type
        self.pipeline_type = pipeline_type
        self.input_type = input_type
        # Best-known wall-clock duration of one run on this worker, in ms.
        # Mutated in place after each successful execution so the heartbeat
        # picks up the latest value.
        self.estimated_time_ms = estimated_time_ms


pipeline_templates: dict[str, PipelineType] = {
    "face_recognition": PipelineType(
        service_type=FaceRecognitionService,
        pipeline_type=FaceRecognitionPipeline,
        input_type=FaceRecognitionPipelineInput,
        estimated_time_ms=1000,
    ),
    "face_swap": PipelineType(
        service_type=FaceSwapService,
        pipeline_type=FaceSwapPipeline,
        input_type=FaceSwapPipelineInput,
        estimated_time_ms=10000,
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
