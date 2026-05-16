"""User photo → Apple ml-sharp 3DGS prediction on Modal.

Modal predicts the 3DGS, packs it into a .splat blob, and uploads
directly to S3; dispatch just bakes EXIF, ships the photo, and forwards
the returned URL + auto-framed camera params. Result is transient — no
SplatScene catalog row; the frontend renders the .splat URL directly
via `?scene_url=&eye=&fwd=`.
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


log = logging.getLogger(__name__)


def _prepare_image_for_modal(image_bytes: bytes) -> tuple[bytes, float]:
    """Bake EXIF + compute f_px from image width. CPU-only, runs in a thread."""

    image_bytes = bake_exif_orientation(image_bytes)
    with Image.open(io.BytesIO(image_bytes)) as img:
        width = img.size[0]
    # No EXIF f_px on most web uploads; default to ~62° FOV (phone main lens).
    f_px = float(width) * 0.9
    return image_bytes, f_px


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
            "image_bucket": self.pipeline_input.image_bucket,
        }

        result = await invoke_sharp(payload)

        result_url = result.get("result_url")
        if not result_url:
            raise RuntimeError(
                f"Modal SHARP endpoint returned no result_url; payload keys: "
                f"{list(result.keys())}"
            )
        gaussian_count = int(result.get("gaussian_count", 0))
        camera_eye = result.get("camera_eye") or [0.0, 0.0, 3.0]
        camera_fwd = result.get("camera_fwd") or [0.0, 0.0, -1.0]

        log.info(
            f"Dispatched sharp complete; {gaussian_count} gaussians at {result_url}"
        )
        return {
            "result_url": result_url,
            "camera_eye": camera_eye,
            "camera_fwd": camera_fwd,
            "gaussian_count": gaussian_count,
        }
