import io
import logging
from typing import List, Optional, Sequence

from PIL import Image

from services.external.face_swap.reactor_api import (
    recognize_faces_api,
    swap_face_api_from_recognition,
)

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(self):
        pass

    def run(self) -> dict:
        raise NotImplementedError


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


def _pick_index_by_bbox(
    bboxes: List[Sequence[float]], target_bbox: Sequence[float]
) -> Optional[int]:
    # Translates a UI-selected bbox into the index understood by
    # swap_face_api_from_recognition, by best-IoU match against the
    # detector's output. None when no positive overlap.
    if not bboxes:
        return None
    best_idx, best_iou = None, 0.0
    for i, b in enumerate(bboxes):
        iou = _bbox_iou(b, target_bbox)
        if iou > best_iou:
            best_iou, best_idx = iou, i
    return best_idx


class FaceRecognitionPipeline(Pipeline):
    def __init__(self, image: bytes):
        Pipeline.__init__(self)
        self.image = image

    def run(self) -> dict:
        # Submodule's recognize_faces_api requires both source and target;
        # for our single-image recognition flow, feed the same PIL image
        # twice and read source_bboxes (target_bboxes mirror them).
        pil = Image.open(io.BytesIO(self.image)).convert("RGB")
        recognition = recognize_faces_api(pil, pil)

        faces: List[dict] = []
        for i, (face, bbox) in enumerate(
            zip(recognition.source_faces, recognition.source_bboxes)
        ):
            det_score = getattr(face, "det_score", None)
            faces.append(
                {
                    "id": f"f{i}",
                    "bbox": [float(v) for v in bbox],
                    "det_score": float(det_score) if det_score is not None else None,
                }
            )

        width, height = pil.size
        return {
            "payload": {
                "image_width": width,
                "image_height": height,
                "faces": faces,
            }
        }


class FaceSwapPipeline(Pipeline):
    def __init__(
        self,
        source_image: bytes,
        target_image: bytes,
        source_face_bbox: Optional[Sequence[float]] = None,
        target_face_bbox: Optional[Sequence[float]] = None,
    ):
        Pipeline.__init__(self)
        self.source_image = source_image
        self.target_image = target_image
        self.source_face_bbox = source_face_bbox
        self.target_face_bbox = target_face_bbox

    def run(self) -> dict:
        source = Image.open(io.BytesIO(self.source_image)).convert("RGB")
        target = Image.open(io.BytesIO(self.target_image)).convert("RGB")

        recognition = recognize_faces_api(source, target)

        # Submodule's swap entrypoint takes face indices, not bboxes.
        # Translate any UI-selected bbox to the matching index; absent or
        # unmatchable bbox falls back to the largest face (index 0).
        source_face_index = 0
        target_face_index = 0
        if self.source_face_bbox is not None:
            idx = _pick_index_by_bbox(
                list(recognition.source_bboxes), self.source_face_bbox
            )
            if idx is not None:
                source_face_index = idx
        if self.target_face_bbox is not None:
            idx = _pick_index_by_bbox(
                list(recognition.target_bboxes), self.target_face_bbox
            )
            if idx is not None:
                target_face_index = idx

        result, _bboxes = swap_face_api_from_recognition(
            recognition,
            model="inswapper_128.onnx",
            source_face_index=source_face_index,
            target_face_index=target_face_index,
            face_boost_model="GFPGANv1.4.pth",
            visibility=1.0,
        )

        output_buffer = io.BytesIO()
        result.save(output_buffer, format="PNG")
        return {"image": output_buffer.getvalue()}
