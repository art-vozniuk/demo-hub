"""User photo → Apple ml-sharp 3DGS prediction on Modal.

Modal returns a 3DGS PLY; PLY→splat, auto-frame and S3 upload run here.
CPU-bound steps go through asyncio.to_thread (~hundreds of ms each)
so they don't block the event loop. NumPy releases the GIL — threads
parallelize fine, no need for a process pool.

Result is transient: no SplatScene catalog row, the frontend renders
the .splat URL straight in an iframe via `?scene_url=&eye=&fwd=`.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
from typing import Any

from PIL import Image

from services.common.s3.client import S3Client

from .base import AsyncPipeline, bake_exif_orientation
from .modal_client import invoke_sharp
from .schemas import SharpPipelineInput
from .sharp_utils import auto_frame_camera, ply_bytes_to_splat_bytes


log = logging.getLogger(__name__)


def _prepare_image_for_modal(image_bytes: bytes) -> tuple[bytes, float]:
    """Bake EXIF + compute f_px from image width. CPU-only, runs in a thread."""

    image_bytes = bake_exif_orientation(image_bytes)
    with Image.open(io.BytesIO(image_bytes)) as img:
        width = img.size[0]
    # No EXIF f_px on most web uploads; default to ~62° FOV (phone main lens).
    f_px = float(width) * 0.9
    return image_bytes, f_px


def _ply_to_splat_and_frame(
    ply_bytes: bytes,
) -> tuple[bytes, int, list[float], list[float]]:
    """Pack splat + auto-frame in one thread hop (shared numpy arrays)."""

    splat_bytes, gaussian_count = ply_bytes_to_splat_bytes(ply_bytes)
    camera_eye, camera_fwd = auto_frame_camera(splat_bytes, gaussian_count)
    return splat_bytes, gaussian_count, camera_eye, camera_fwd


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

        t_prep = time.perf_counter()
        image_bytes, f_px = await asyncio.to_thread(
            _prepare_image_for_modal, image_bytes
        )
        log.info(
            "sharp: prep image done in %.0fms (f_px=%.1f)",
            (time.perf_counter() - t_prep) * 1000,
            f_px,
        )

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

        t_post = time.perf_counter()
        splat_bytes, gaussian_count, camera_eye, camera_fwd = await asyncio.to_thread(
            _ply_to_splat_and_frame, ply_bytes
        )
        log.info(
            "sharp: ply→splat + auto-frame done in %.0fms "
            "(%d gaussians, %.1f MB)",
            (time.perf_counter() - t_post) * 1000,
            gaussian_count,
            len(splat_bytes) / (1024 * 1024),
        )

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
