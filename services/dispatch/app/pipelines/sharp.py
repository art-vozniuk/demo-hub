"""User photo → Apple ml-sharp 3DGS prediction on Modal.

Modal runs the GPU forward pass and returns a standard 3DGS PLY.
Everything else — PLY → 32-byte/gaussian .splat packing, initial-camera
auto-framing from the gaussian point cloud, and the S3 upload — happens
here on CPU. Keeps the Modal image lean and reuses the plyfile/numpy
stack we already need on the dispatch side.

No SplatScene catalog row is created; SHARP results are transient,
keyed by the pipeline id. The frontend reads result_url + camera
vectors out of the pipeline result JSON and renders the splat directly
in an iframe pointed at the WASM viewer with
`?scene_url=...&eye=...&fwd=...`.
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Any

from PIL import Image

from services.common.s3.client import S3Client

from .base import AsyncPipeline, bake_exif_orientation
from .modal_client import invoke_sharp
from .schemas import SharpPipelineInput
from .sharp_utils import auto_frame_camera, ply_bytes_to_splat_bytes


log = logging.getLogger(__name__)


class SharpPipeline(AsyncPipeline):
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

        # Bake EXIF orientation in here so Modal never has to think about
        # it; same trap as FLUX.
        image_bytes = bake_exif_orientation(image_bytes)

        # Read the image's width on our side and compute f_px. SHARP's
        # predictor needs a focal length in pixels; EXIF is usually
        # stripped on web-uploaded photos, so we fall back to ~62°
        # horizontal FOV (typical phone main lens). Pushing this
        # calculation to dispatch keeps the Modal container at pure
        # GPU + image decode.
        with Image.open(io.BytesIO(image_bytes)) as img:
            width = img.size[0]
        f_px = float(width) * 0.9

        payload = {
            "image_b64": base64.b64encode(image_bytes).decode("ascii"),
            "f_px": f_px,
        }

        result = await invoke_sharp(payload)

        ply_b64 = result.get("ply_b64")
        if not ply_b64:
            raise RuntimeError(
                f"Modal SHARP endpoint returned no ply_b64; payload keys: "
                f"{list(result.keys())}"
            )
        ply_bytes = base64.b64decode(ply_b64)

        splat_bytes, gaussian_count = ply_bytes_to_splat_bytes(ply_bytes)
        camera_eye, camera_fwd = auto_frame_camera(splat_bytes, gaussian_count)

        url = await self.s3.upload_file(
            data_bytes=splat_bytes,
            s3_bucket=self.pipeline_input.image_bucket,
            s3_folder="sharp_results",
            file_extension="splat",
        )

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
