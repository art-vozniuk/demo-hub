"""Shared base for async dispatch pipelines.

Each Pipeline is purely IO-bound — it fetches inputs, calls a remote
inference service, uploads the result, and returns a structured payload
identical in shape to compute pipelines. Concrete pipelines live in
sibling modules (`generative_editing.py`, `sharp.py`).
"""

from __future__ import annotations

import io
from typing import Any

from PIL import Image, ImageOps


class AsyncPipeline:
    async def run(self) -> dict[str, Any]:
        raise NotImplementedError


def bake_exif_orientation(image_bytes: bytes) -> bytes:
    """Apply EXIF Orientation and re-encode as JPEG.

    Most remote inference backends (FLUX, SHARP) open images via PIL and
    drop the Orientation tag, so phone-portrait JPEGs arrive sideways
    unless we bake the rotation in here. Cheap to do on dispatch.
    """

    with Image.open(io.BytesIO(image_bytes)) as img:
        oriented = ImageOps.exif_transpose(img)
        if oriented.mode != "RGB":
            oriented = oriented.convert("RGB")
        out = io.BytesIO()
        oriented.save(out, format="JPEG", quality=95)
        return out.getvalue()
