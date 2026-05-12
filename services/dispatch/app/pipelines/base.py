"""Shared base for async dispatch pipelines. Concrete classes live in
sibling modules (generative_editing.py, sharp.py)."""

from __future__ import annotations

import io
from typing import Any

from PIL import Image, ImageOps


class AsyncPipeline:
    async def run(self) -> dict[str, Any]:
        raise NotImplementedError


def bake_exif_orientation(image_bytes: bytes) -> bytes:
    """Apply EXIF Orientation and re-encode JPEG — backends drop the tag,
    leaving phone-portrait shots sideways unless we bake it in here."""

    with Image.open(io.BytesIO(image_bytes)) as img:
        oriented = ImageOps.exif_transpose(img)
        if oriented.mode != "RGB":
            oriented = oriented.convert("RGB")
        out = io.BytesIO()
        oriented.save(out, format="JPEG", quality=95)
        return out.getvalue()
