"""User photo → Apple ml-sharp 3DGS prediction on Modal.

Dispatch only forwards the S3 location of the source photo to Modal;
Modal downloads, bakes EXIF, computes f_px, runs inference, packs the
.splat, and uploads it back to S3 itself. Dispatch never sees the
image bytes — it forwards the result URL + auto-framed camera params.
"""

from __future__ import annotations

import logging
from typing import Any

from services.common.s3.client import S3Client

from .base import AsyncPipeline
from .modal_client import invoke_sharp
from .schemas import SharpPipelineInput


log = logging.getLogger(__name__)


class SharpPipeline(AsyncPipeline):
    def __init__(
        self,
        s3: S3Client,
        pipeline_input: SharpPipelineInput,
    ) -> None:
        # s3 is plumbed in by the service factory but unused — Modal owns
        # both the download and the upload now.
        self.s3 = s3
        self.pipeline_input = pipeline_input

    async def run(self) -> dict[str, Any]:
        payload = {
            "image_bucket": self.pipeline_input.image_bucket,
            "image_key": self.pipeline_input.image_key,
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
        # Optional wobble-preview MP4; Modal returns null when RENDER_VIDEO is off.
        video_url = result.get("video_url")

        log.info(
            f"Dispatched sharp complete; {gaussian_count} gaussians at {result_url}"
            + (f" (video={video_url})" if video_url else "")
        )
        return {
            "result_url": result_url,
            "video_url": video_url,
            "camera_eye": camera_eye,
            "camera_fwd": camera_fwd,
            "gaussian_count": gaussian_count,
        }
