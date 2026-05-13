"""Modal app: Apple ml-sharp single-image → 3DGS on A10G.

GPU inference only — PLY→splat, auto-frame and S3 upload run on
dispatch. Endpoint: POST {image_b64, f_px} → {ply_b64, ply_size_bytes}.
Deploy / preload via services/modal/scripts/{deploy,preload}-sharp.sh.
"""

from __future__ import annotations

import base64
import io
import os
import tempfile
import time
import urllib.request
import uuid
from typing import Any

import modal

from _common import MODEL_DIR, configure_logging, make_app


CHECKPOINT_URL = "https://ml-site.cdn-apple.com/models/sharp/sharp_2572gikvuh.pt"
CHECKPOINT_LOCAL_PATH = f"{MODEL_DIR}/sharp_2572gikvuh.pt"


log = configure_logging("sharp")
app, volume = make_app("demo-hub-sharp", "sharp-models")


# ml-sharp recommends Python 3.13. torch 2.5.x has 3.13 wheels but matching
# torchvision 0.20.x does not — bump the pair to 2.6/0.21, the first with
# cp313 wheels on both sides.
sharp_image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("git", "libgl1", "libglib2.0-0")
    .pip_install(
        "torch==2.6.0",
        "torchvision==0.21.0",
        "numpy",
        "Pillow==11.0.0",
        "click",
        "fastapi[standard]==0.115.6",
        "pydantic==2.10.3",
        # ml-sharp is GitHub-only; pin to a commit once Apple ships a release.
        "git+https://github.com/apple/ml-sharp.git",
    )
    # Modal no longer auto-mounts sibling .py files; ship _common explicitly.
    .add_local_python_source("_common")
)


with sharp_image.imports():
    import numpy as np
    import torch
    from PIL import Image
    from sharp.models import PredictorParams, create_predictor
    from sharp.utils.gaussians import save_ply


def _ensure_checkpoint() -> str:
    """Download the SHARP checkpoint into the volume on first call. Idempotent."""

    if os.path.exists(CHECKPOINT_LOCAL_PATH):
        log.info(f"checkpoint cached at {CHECKPOINT_LOCAL_PATH}")
        return CHECKPOINT_LOCAL_PATH

    log.info(f"downloading checkpoint from {CHECKPOINT_URL} -> {CHECKPOINT_LOCAL_PATH}")
    os.makedirs(MODEL_DIR, exist_ok=True)
    # Tmp + rename so a killed container can't leave a half-file in the cache.
    tmp = CHECKPOINT_LOCAL_PATH + ".tmp"

    # Apple's CDN occasionally resets the TLS handshake mid-download; retry
    # with exponential backoff before giving up.
    max_attempts = 5
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        t0 = time.perf_counter()
        try:
            urllib.request.urlretrieve(CHECKPOINT_URL, tmp)
            os.replace(tmp, CHECKPOINT_LOCAL_PATH)
            size_mb = os.path.getsize(CHECKPOINT_LOCAL_PATH) / (1024 * 1024)
            log.info(
                f"checkpoint downloaded ({size_mb:.1f} MB) "
                f"in {(time.perf_counter() - t0):.1f}s (attempt {attempt})"
            )
            return CHECKPOINT_LOCAL_PATH
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            last_err = e
            elapsed = time.perf_counter() - t0
            sleep_s = min(2**attempt, 30)
            log.warning(
                f"download attempt {attempt}/{max_attempts} failed after "
                f"{elapsed:.1f}s: {e!r}; retrying in {sleep_s}s"
            )
            # Drop any partial tmp so the next attempt starts clean.
            try:
                os.remove(tmp)
            except FileNotFoundError:
                pass
            if attempt < max_attempts:
                time.sleep(sleep_s)

    raise RuntimeError(
        f"failed to download checkpoint after {max_attempts} attempts: {last_err!r}"
    )


@app.function(
    image=sharp_image,
    volumes={MODEL_DIR: volume},
    timeout=60 * 30,
    cpu=4.0,
    memory=8192,
)
def preload_weights() -> str:
    """One-shot: populate the sharp-models volume. Re-running is a no-op."""

    path = _ensure_checkpoint()
    volume.commit()
    log.info(f"volume.commit done; checkpoint at {path}")
    return path


@app.cls(
    image=sharp_image,
    gpu="A10G",
    volumes={MODEL_DIR: volume},
    scaledown_window=10,
    timeout=600,
    enable_memory_snapshot=True,
)
@modal.concurrent(max_inputs=1)
class SharpInference:
    @modal.enter(snap=True)
    def load_to_cpu(self) -> None:
        """Snapshot hook: load weights into CPU RAM once; cold starts restore from RAM."""

        log.info("snapshot-load: load_to_cpu() begin (CPU-only container)")
        t0 = time.perf_counter()

        ckpt_path = _ensure_checkpoint()
        state_dict = torch.load(ckpt_path, weights_only=True, map_location="cpu")
        load_ms = (time.perf_counter() - t0) * 1000
        log.info(f"snapshot-load: torch.load done in {load_ms:.0f}ms")

        t1 = time.perf_counter()
        self.predictor = create_predictor(PredictorParams())
        self.predictor.load_state_dict(state_dict)
        self.predictor.eval()
        init_ms = (time.perf_counter() - t1) * 1000
        log.info(
            f"snapshot-load: create_predictor + load_state_dict done "
            f"in {init_ms:.0f}ms"
        )

    @modal.enter(snap=False)
    def move_to_gpu(self) -> None:
        """Post-restore hook: shuttle preloaded weights to the GPU."""

        log.info("post-restore: move_to_gpu() begin (GPU now attached)")
        t0 = time.perf_counter()
        self.predictor.to("cuda")
        to_cuda_ms = (time.perf_counter() - t0) * 1000
        log.info(f"post-restore: predictor.to(cuda) done in {to_cuda_ms:.0f}ms")

    @modal.method()
    def generate(
        self,
        image_b64: str,
        request_id: str,
        f_px: float,
    ) -> dict[str, Any]:
        log.info(f"[{request_id}] inference: start; f_px={f_px:.1f}")
        t0 = time.perf_counter()

        # Image arrives EXIF-baked from dispatch; just decode to an HWC numpy.
        raw = base64.b64decode(image_b64)
        pil = Image.open(io.BytesIO(raw)).convert("RGB")
        arr = np.array(pil)
        height, width = arr.shape[:2]
        log.info(f"[{request_id}] input: {width}x{height}, {len(raw)} bytes")

        t_inf = time.perf_counter()
        gaussians = self._run_inference(arr, f_px)
        inference_ms = (time.perf_counter() - t_inf) * 1000
        log.info(
            f"[{request_id}] inference: predict_image done in "
            f"{inference_ms:.0f}ms"
        )

        # save_ply stays here — it needs the `sharp` package's linearRGB→sRGB
        # and opacity→logit conversions tied to the predictor's tensors.
        with tempfile.TemporaryDirectory() as td:
            ply_path = f"{td}/scene.ply"
            t_save = time.perf_counter()
            save_ply(gaussians, f_px, (height, width), ply_path)
            ply_bytes = open(ply_path, "rb").read()
            log.info(
                f"[{request_id}] save_ply done in "
                f"{(time.perf_counter() - t_save) * 1000:.0f}ms; "
                f"size={len(ply_bytes) / (1024 * 1024):.1f} MB"
            )

        total_ms = (time.perf_counter() - t0) * 1000
        log.info(
            f"[{request_id}] inference: done in {total_ms:.0f}ms "
            f"(inference={inference_ms:.0f}ms)"
        )

        return {
            "ply_b64": base64.b64encode(ply_bytes).decode("ascii"),
            "ply_size_bytes": len(ply_bytes),
        }

    def _run_inference(self, image: "np.ndarray", f_px: float) -> Any:
        """Inlined copy of sharp.cli.predict.predict_image — that lives under
        cli/ and isn't a stable API. Revisit when Apple ships one."""

        # torch is imported inside `sharp_image.imports()` so it's unavailable
        # when this file is parsed locally — keep no_grad as a context manager
        # inside the body, not a decorator on the def.
        import torch.nn.functional as F  # noqa: N812
        from sharp.utils.gaussians import unproject_gaussians

        with torch.no_grad():
            device = torch.device("cuda")
            internal_shape = (1536, 1536)

            image_pt = (
                torch.from_numpy(image.copy()).float().to(device).permute(2, 0, 1)
                / 255.0
            )
            _, height, width = image_pt.shape
            disparity_factor = torch.tensor([f_px / width]).float().to(device)

            image_resized_pt = F.interpolate(
                image_pt[None],
                size=(internal_shape[1], internal_shape[0]),
                mode="bilinear",
                align_corners=True,
            )

            gaussians_ndc = self.predictor(image_resized_pt, disparity_factor)

            intrinsics = (
                torch.tensor(
                    [
                        [f_px, 0, width / 2, 0],
                        [0, f_px, height / 2, 0],
                        [0, 0, 1, 0],
                        [0, 0, 0, 1],
                    ]
                )
                .float()
                .to(device)
            )
            intrinsics_resized = intrinsics.clone()
            intrinsics_resized[0] *= internal_shape[0] / width
            intrinsics_resized[1] *= internal_shape[1] / height

            return unproject_gaussians(
                gaussians_ndc,
                torch.eye(4).to(device),
                intrinsics_resized,
                internal_shape,
            )


@app.function(
    image=sharp_image,
    timeout=600,
)
@modal.fastapi_endpoint(method="POST", requires_proxy_auth=True)
def generate(payload: dict[str, Any]) -> dict[str, Any]:
    """Public HTTP entry point; proxy-auth gated by Modal."""

    request_id = uuid.uuid4().hex[:8]
    t0 = time.perf_counter()

    image_b64 = payload.get("image_b64")
    f_px = payload.get("f_px")
    log.info(
        f"[{request_id}] endpoint: POST received; "
        f"image_b64_len={len(image_b64) if image_b64 else 0} f_px={f_px}"
    )

    if not image_b64:
        log.warning(f"[{request_id}] endpoint: rejecting; missing image_b64")
        return {"error": "image_b64 is required"}
    if f_px is None:
        log.warning(f"[{request_id}] endpoint: rejecting; missing f_px")
        return {"error": "f_px is required"}

    inference = SharpInference()
    result = inference.generate.remote(
        request_id=request_id,
        image_b64=image_b64,
        f_px=float(f_px),
    )

    total_ms = (time.perf_counter() - t0) * 1000
    log.info(
        f"[{request_id}] endpoint: done; total_ms={total_ms:.0f} "
        f"ply_bytes={result.get('ply_size_bytes') if isinstance(result, dict) else 0}"
    )
    return result
