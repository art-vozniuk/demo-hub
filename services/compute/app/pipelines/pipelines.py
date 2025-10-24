import io
import logging

from PIL import Image

from services.external.face_swap.reactor_api import swap_face_api

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(self):
        pass

    def run(self) -> dict:
        raise NotImplementedError


class RecastPipeline(Pipeline):
    def __init__(self, source_image: bytes, target_image: bytes):
        Pipeline.__init__(self)

        self.source_image = source_image
        self.target_image = target_image

    def run(self) -> dict:
        source = Image.open(io.BytesIO(self.source_image)).convert("RGB")
        target = Image.open(io.BytesIO(self.target_image)).convert("RGB")

        result, bboxes = swap_face_api(
            source=source,
            target=target,
            model="inswapper_128.onnx",
            source_face_index=0,
            target_face_index=0,
            face_boost_model="GFPGANv1.4.pth",
            visibility=1.0,
        )

        output_buffer = io.BytesIO()
        result.save(output_buffer, format="PNG")
        return {"image": output_buffer.getvalue()}
