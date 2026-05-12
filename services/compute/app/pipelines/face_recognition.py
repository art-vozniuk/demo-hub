"""Detect faces in one image and return their bboxes for the UI."""

from __future__ import annotations

import io
import logging
from typing import List

from PIL import Image, ImageOps

from services.external.face_swap.reactor_api import detect_faces

from .base import Pipeline


log = logging.getLogger(__name__)


class FaceRecognitionPipeline(Pipeline):
    def __init__(self, image: bytes) -> None:
        super().__init__()
        self.image = image

    def run(self) -> dict:
        # Bake EXIF Orientation so face bboxes match what the user sees.
        pil = ImageOps.exif_transpose(Image.open(io.BytesIO(self.image))).convert("RGB")
        faces = detect_faces(pil)

        out_faces: List[dict] = []
        for i, face in enumerate(faces):
            det_score = getattr(face, "det_score", None)
            out_faces.append(
                {
                    "id": f"f{i}",
                    "bbox": [float(v) for v in face.bbox],
                    "det_score": float(det_score) if det_score is not None else None,
                }
            )

        width, height = pil.size
        return {
            "payload": {
                "image_width": width,
                "image_height": height,
                "faces": out_faces,
            }
        }
