"""Modal app: Apple ml-sharp single-image → 3DGS on A10G.

predict → pack Gaussians3D into 32-byte splat blob → auto-frame → S3
upload, all on the GPU container; dispatch only forwards the result.
Endpoint-less: invoked by name through the gateway.
Deploy / preload via services/modal/sharp/{deploy,preload}.py.
"""

from __future__ import annotations

import io
import os
import time
import urllib.request
from typing import Any

import modal

from common.constants import MODAL_FUNCTION_TIMEOUT_SECONDS
from common.instrument import InferenceRunner
from common.lib import (
    MODEL_DIR,
    bake_exif_orientation,
    configure_logging,
    download_from_s3,
    make_app,
    upload_to_s3,
)
from common.sentry import init_sentry


GPU_NAME = "A10G"
SCALEDOWN_WINDOW_S = 10

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
        "plyfile==1.0.3",
        "Pillow==11.0.0",
        "click",
        "fastapi[standard]==0.115.6",
        "pydantic==2.10.3",
        "boto3==1.35.92",
        "sentry-sdk>=2.42.0",
        # ml-sharp is GitHub-only; pin to a commit once Apple ships a release.
        "git+https://github.com/apple/ml-sharp.git",
    )
    # Modal no longer auto-mounts sibling files; ship common.lib +
    # common.sharp_utils explicitly. (sharp_utils lives under common/
    # rather than sharp/ to avoid clashing with the ml-sharp pip
    # package's own `sharp` namespace.)
    .add_local_python_source(
        "common.lib",
        "common.sharp_utils",
        "common.instrument",
        "common.constants",
        "common.sentry",
    )
)


with sharp_image.imports():
    import numpy as np
    import torch
    from PIL import Image
    from sharp.models import PredictorParams, create_predictor
    from common.sharp_utils import auto_frame_camera, gaussians_to_splat_bytes


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
    gpu=GPU_NAME,
    volumes={MODEL_DIR: volume},
    scaledown_window=SCALEDOWN_WINDOW_S,
    timeout=MODAL_FUNCTION_TIMEOUT_SECONDS,
    enable_memory_snapshot=True,
    secrets=[
        modal.Secret.from_name("supabase-s3"),
        modal.Secret.from_name("sentry"),
    ],
    #min_containers=1,
)
@modal.concurrent(max_inputs=1)
class SharpInference:
    @modal.enter(snap=True)
    def load_to_cpu(self) -> None:
        """Snapshot hook: load weights into CPU RAM once; cold starts restore from RAM."""

        log.info("snapshot-load: load_to_cpu() begin (CPU-only container)")
        t_snap = time.perf_counter()

        ckpt_path = _ensure_checkpoint()
        t0 = time.perf_counter()
        # mmap + assign: weights stay file-backed instead of bloating the
        # memory snapshot — restore reads MB, not GB.
        state_dict = torch.load(
            ckpt_path, weights_only=True, map_location="cpu", mmap=True
        )
        load_ms = (time.perf_counter() - t0) * 1000
        log.info(f"snapshot-load: torch.load done in {load_ms:.0f}ms")

        t1 = time.perf_counter()
        self.predictor = create_predictor(PredictorParams())
        self.predictor.load_state_dict(state_dict, assign=True)
        self.predictor.eval()
        init_ms = (time.perf_counter() - t1) * 1000
        self._snapshot_load_s = time.perf_counter() - t_snap
        log.info(
            f"snapshot-load: create_predictor + load_state_dict done "
            f"in {init_ms:.0f}ms (snapshot total {self._snapshot_load_s:.1f}s)"
        )

    @modal.enter(snap=False)
    def move_to_gpu(self) -> None:
        """Post-restore hook: shuttle preloaded weights to the GPU."""

        init_sentry("sharp")
        log.info("post-restore: move_to_gpu() begin (GPU now attached)")
        t0 = time.perf_counter()
        self.predictor.to("cuda")
        to_cuda_s = time.perf_counter() - t0
        log.info(f"post-restore: predictor.to(cuda) done in {to_cuda_s * 1000:.0f}ms")

        # Built here (snap=False) so each container gets its own identity.
        self.runner = InferenceRunner(
            config="sharp",
            gpu=GPU_NAME,
            scaledown_window_s=SCALEDOWN_WINDOW_S,
            log=log,
            cold={
                "snapshot_load": getattr(self, "_snapshot_load_s", 0.0),
                "to_cuda": to_cuda_s,
            },
        )

    @modal.method()
    def generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        image_bucket = payload["image_bucket"]
        image_key = payload["image_key"]

        with self.runner.start(payload) as run:
            log.info(f"[{run.request_id}] inference: start; key={image_key}")

            with run.phase("download"):
                raw = download_from_s3(image_bucket, image_key)
                raw = bake_exif_orientation(raw)

            pil = Image.open(io.BytesIO(raw)).convert("RGB")
            arr = np.array(pil)
            height, width = arr.shape[:2]
            # No EXIF f_px on most web uploads; default to ~62° FOV (phone main lens).
            f_px = float(width) * 0.9
            log.info(
                f"[{run.request_id}] input: {width}x{height}, f_px={f_px:.1f}"
            )

            with run.phase("gpu"):
                gaussians = self._run_inference(arr, f_px)

            with run.phase("pack"):
                splat_bytes, gaussian_count, pos_np, alpha_np = (
                    gaussians_to_splat_bytes(gaussians)
                )
                camera_eye, camera_fwd = auto_frame_camera(pos_np, alpha_np)
            log.info(
                f"[{run.request_id}] splat_size="
                f"{len(splat_bytes) / (1024 * 1024):.1f} MB "
                f"({gaussian_count} gaussians)"
            )

            with run.phase("upload"):
                result_url = upload_to_s3(
                    data_bytes=splat_bytes,
                    bucket=image_bucket,
                    folder="sharp_results",
                    extension="splat",
                )

            run.batch(1)
            return run.finish(
                {
                    "result_url": result_url,
                    "splat_size_bytes": len(splat_bytes),
                    "gaussian_count": gaussian_count,
                    "camera_eye": camera_eye,
                    "camera_fwd": camera_fwd,
                }
            )

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
