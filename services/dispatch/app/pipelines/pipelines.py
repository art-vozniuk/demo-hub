"""Async dispatch pipelines. Each Pipeline is purely IO-bound — it
fetches inputs, calls a remote inference service, uploads the result,
and returns a structured payload identical in shape to compute pipelines.
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Any

from PIL import Image, ImageOps

from services.common.s3.client import S3Client

from .modal_client import invoke_generative_editing, invoke_sharp
from .schemas import GenerativeEditingPipelineInput, SharpPipelineInput

log = logging.getLogger(__name__)


class AsyncPipeline:
    async def run(self) -> dict[str, Any]:
        raise NotImplementedError


def _bake_exif_orientation(image_bytes: bytes) -> bytes:
    # FLUX's PIL.Image.open drops the EXIF Orientation tag, so phone-portrait
    # JPEGs reach the model sideways unless we bake the rotation in here.
    with Image.open(io.BytesIO(image_bytes)) as img:
        oriented = ImageOps.exif_transpose(img)
        if oriented.mode != "RGB":
            oriented = oriented.convert("RGB")
        out = io.BytesIO()
        oriented.save(out, format="JPEG", quality=95)
        return out.getvalue()


class GenerativeEditingPipeline(AsyncPipeline):
    """User photo → FLUX.2 klein image-conditioned edit on Modal."""

    def __init__(
        self,
        s3: S3Client,
        pipeline_input: GenerativeEditingPipelineInput,
    ) -> None:
        self.s3 = s3
        self.pipeline_input = pipeline_input

    async def run(self) -> dict[str, Any]:
        image_bytes = await self.s3.download_file(
            s3_bucket=self.pipeline_input.image_bucket,
            s3_key=self.pipeline_input.image_key,
        )

        image_bytes = _bake_exif_orientation(image_bytes)

        payload = {
            "image_b64": base64.b64encode(image_bytes).decode("ascii"),
            "prompt": self.pipeline_input.prompt,
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


class SharpPipeline(AsyncPipeline):
    """User photo → Apple ml-sharp 3DGS prediction on Modal.

    Modal returns a base64-encoded .splat blob (32 bytes/gaussian) plus
    an auto-framed initial camera. We persist the splat to S3 and bundle
    the result URL with the camera vectors in the pipeline result JSON —
    the frontend reads those and renders the splat in an iframe pointed
    at the WASM viewer with `?scene_url=...&eye=...&fwd=...`. No
    SplatScene catalog row is created; SHARP results are transient,
    keyed by the pipeline id.
    """

    def __init__(
        self,
        s3: S3Client,
        pipeline_input: SharpPipelineInput,
    ) -> None:
        self.s3 = s3
        self.pipeline_input = pipeline_input

    async def run(self) -> dict[str, Any]:
        image_bytes = await self.s3.download_file(
            s3_bucket=self.pipeline_input.image_bucket,
            s3_key=self.pipeline_input.image_key,
        )

        # Bake EXIF orientation in here too — SHARP's preprocessing path
        # drops the tag, same trap as FLUX. Cheaper to fix on dispatch
        # than to round-trip a sideways portrait through 1.5s of GPU.
        image_bytes = _bake_exif_orientation(image_bytes)

        payload = {
            "image_b64": base64.b64encode(image_bytes).decode("ascii"),
        }

        result = await invoke_sharp(payload)

        splat_b64 = result.get("splat_b64")
        if not splat_b64:
            raise RuntimeError(
                f"Modal SHARP endpoint returned no splat_b64; payload keys: "
                f"{list(result.keys())}"
            )

        splat_bytes = base64.b64decode(splat_b64)
        url = await self.s3.upload_file(
            data_bytes=splat_bytes,
            s3_bucket=self.pipeline_input.image_bucket,
            s3_folder="sharp_results",
            file_extension="splat",
        )

        camera_eye = result.get("camera_eye") or [0.0, 0.0, 0.0]
        camera_fwd = result.get("camera_fwd") or [0.0, 0.0, 1.0]
        gaussian_count = result.get("gaussian_count")

        log.info(
            f"Dispatched sharp complete; uploaded {len(splat_bytes)} bytes "
            f"({gaussian_count} gaussians) to {url}"
        )
        return {
            "result_url": url,
            "camera_eye": camera_eye,
            "camera_fwd": camera_fwd,
            "gaussian_count": gaussian_count,
        }
