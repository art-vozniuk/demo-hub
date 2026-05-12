"""Swap a chosen source face onto a target image using the Reactor pipeline."""

from __future__ import annotations

import io
import logging
from typing import List, Optional, Sequence

from PIL import Image, ImageOps
from insightface.app.common import Face

from services.external.face_swap.reactor_api import (
    detect_faces,
    swap_specific_face,
)

from .base import Pipeline


log = logging.getLogger(__name__)


def _bbox_iou(a: Sequence[float], b: Sequence[float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _pick_face_by_bbox(
    faces: List[Face], target_bbox: Sequence[float]
) -> Optional[Face]:
    # The recognition pipeline gave the UI bboxes; the user picked one and
    # sent it back. Detection isn't carried across pipelines (Face objects
    # have heavy embeddings), so the swap pipeline re-detects and matches
    # the UI's bbox to a fresh Face by best IoU. Returns None when nothing
    # overlaps — caller decides the fallback.
    if not faces:
        return None
    best, best_iou = None, 0.0
    for f in faces:
        iou = _bbox_iou(f.bbox, target_bbox)
        if iou > best_iou:
            best_iou, best = iou, f
    return best


class FaceSwapPipeline(Pipeline):
    def __init__(
        self,
        source_image: bytes,
        target_image: bytes,
        source_face_bbox: Optional[Sequence[float]] = None,
        target_face_bbox: Optional[Sequence[float]] = None,
    ) -> None:
        super().__init__()
        self.source_image = source_image
        self.target_image = target_image
        self.source_face_bbox = source_face_bbox
        self.target_face_bbox = target_face_bbox

    def run(self) -> dict:
        source = ImageOps.exif_transpose(
            Image.open(io.BytesIO(self.source_image))
        ).convert("RGB")
        target = ImageOps.exif_transpose(
            Image.open(io.BytesIO(self.target_image))
        ).convert("RGB")

        source_faces = detect_faces(source)
        target_faces = detect_faces(target)

        if not source_faces:
            raise RuntimeError("face_swap: no faces detected in source image")
        if not target_faces:
            raise RuntimeError("face_swap: no faces detected in target image")

        # If the caller pre-selected faces (UI flow), match by bbox; otherwise
        # — and on stale-bbox misses — fall back to the first detected face.
        source_face: Face = (
            _pick_face_by_bbox(source_faces, self.source_face_bbox)
            if self.source_face_bbox is not None
            else None
        ) or source_faces[0]
        target_face: Face = (
            _pick_face_by_bbox(target_faces, self.target_face_bbox)
            if self.target_face_bbox is not None
            else None
        ) or target_faces[0]

        result = swap_specific_face(
            target_img=target,
            source_face=source_face,
            target_face=target_face,
            model="inswapper_128.onnx",
            face_boost_model="GFPGANv1.4.pth",
            visibility=1,
        )

        output_buffer = io.BytesIO()
        result.save(output_buffer, format="PNG")
        return {"image": output_buffer.getvalue()}
