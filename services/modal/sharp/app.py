"""Modal app: Apple ml-sharp single-image → 3DGS on A10G.

predict → pack Gaussians3D into 32-byte splat blob → auto-frame → S3
upload, all on the GPU container; dispatch only forwards the result.
Two HTTP endpoints to dodge Modal's ~60s sync gateway cap:
  POST /submit {image_b64, f_px, image_bucket} → {call_id, request_id}
  POST /poll   {call_id}                       → {status: ..., ...}
Deploy / preload via services/modal/sharp/{deploy,preload}.py.
"""

from __future__ import annotations

import io
import os
import time
import urllib.request
import uuid
from typing import Any

import modal

from common.lib import (
    MODEL_DIR,
    bake_exif_orientation,
    configure_logging,
    download_from_s3,
    make_app,
    poll_function_call,
    upload_to_s3,
)
from common.prebuild_gsplat import prebuild as _prebuild_gsplat_kernels


CHECKPOINT_URL = "https://ml-site.cdn-apple.com/models/sharp/sharp_2572gikvuh.pt"
CHECKPOINT_LOCAL_PATH = f"{MODEL_DIR}/sharp_2572gikvuh.pt"


log = configure_logging("sharp")
app, volume = make_app("demo-hub-sharp", "sharp-models")


# Flip to False to skip the wobble-MP4 preview render (and shave the
# gsplat/imageio cost off the inference path). Image deps are still
# baked in regardless, so toggling does NOT require an image rebuild —
# only the per-call extra ~1-3s on the GPU goes away.
RENDER_VIDEO = True


# ml-sharp recommends Python 3.13. torch 2.5.x has 3.13 wheels but matching
# torchvision 0.20.x does not — bump the pair to 2.6/0.21, the first with
# cp313 wheels on both sides.
#
# Base = nvidia/cuda:12.4.1-devel: gsplat builds CUDA kernels at
# `pip install` time and needs `nvcc` + CUDA headers. The matching
# `cu124`-built torch wheel links its own CUDA runtime so we don't
# rely on system libs at execution time, only at build.
sharp_image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.4.1-devel-ubuntu22.04",
        add_python="3.13",
    )
    .apt_install("git", "libgl1", "libglib2.0-0", "ffmpeg")
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
        # Wobble-preview MP4 render. gsplat ships only a py3-none-any
        # wrapper and JIT-compiles its CUDA kernels via torch's
        # cpp_extension on first call — we trigger that compile in
        # .run_function below so each cold start doesn't pay it.
        "gsplat==1.4.0",
        "imageio[ffmpeg]==2.36.1",
        # ml-sharp is GitHub-only; pin to a commit once Apple ships a release.
        "git+https://github.com/apple/ml-sharp.git",
    )
    .env(
        {
            # Narrow gsplat's nvcc compile to A10G (sm_86). Without
            # this, nvcc compiles for every arch torch advertises,
            # 5-10× slower build.
            "TORCH_CUDA_ARCH_LIST": "8.6",
            # Pin torch's JIT cache to a path that's part of the image
            # layer (default `~/.cache/torch_extensions` works too on
            # Modal, but being explicit guards against future $HOME
            # changes upstream).
            "TORCH_EXTENSIONS_DIR": "/root/torch_extensions",
        }
    )
    # prebuild_gsplat is consumed by `.run_function` below — must be
    # baked in (copy=True) since Modal forbids `add_local_*` before
    # additional build steps without copying.
    .add_local_python_source("common.prebuild_gsplat", copy=True)
    # Bake gsplat's CUDA kernels into the image layer (~1-2 min A10G
    # at build time); without this, cold starts wait ~1-3 min on JIT.
    .run_function(_prebuild_gsplat_kernels, gpu="A10G")
    # Rest is attached at container startup (no rebuild on edits).
    # sharp_utils lives under common/ rather than sharp/ to avoid
    # clashing with the ml-sharp pip package's own `sharp` namespace.
    # prebuild_gsplat is intentionally listed in BOTH add_local steps:
    # the copy=True one above makes it available to .run_function at
    # build time; this one ensures sharp/app.py's top-level
    # `from common.prebuild_gsplat import ...` resolves at runtime
    # (otherwise the runtime-attached `common/` shadows the baked-in
    # one and the prebuild module disappears from sys.path).
    .add_local_python_source(
        "common.lib",
        "common.sharp_utils",
        "common.sharp_video",
        "common.prebuild_gsplat",
    )
)


# submit/poll only spawn / inspect a FunctionCall — no torch needed. A
# thin image keeps their cold-start small. common.lib ships here because
# the module top-level calls `configure_logging` and `make_app` on every
# container start; sharp_utils is gated behind `sharp_image.imports()`
# so it never loads outside the inference container.
sharp_thin_image = (
    modal.Image.debian_slim(python_version="3.13")
    .pip_install(
        "fastapi[standard]==0.115.6",
        "pydantic==2.10.3",
    )
    .add_local_python_source("common.lib")
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
    gpu="A10G",
    volumes={MODEL_DIR: volume},
    scaledown_window=10,
    timeout=600,
    enable_memory_snapshot=True,
    secrets=[modal.Secret.from_name("supabase-s3")],
    #min_containers=1,
)
@modal.concurrent(max_inputs=1)
class SharpInference:
    @modal.enter(snap=True)
    def load_to_cpu(self) -> None:
        """Snapshot hook: load weights into CPU RAM once; cold starts restore from RAM."""

        log.info("snapshot-load: load_to_cpu() begin (CPU-only container)")
        t0 = time.perf_counter()

        ckpt_path = _ensure_checkpoint()
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
        image_bucket: str,
        image_key: str,
        request_id: str,
    ) -> dict[str, Any]:
        log.info(f"[{request_id}] inference: start; key={image_key}")
        t0 = time.perf_counter()

        t_dl = time.perf_counter()
        raw = download_from_s3(image_bucket, image_key)
        raw = bake_exif_orientation(raw)
        log.info(
            f"[{request_id}] s3 download + EXIF bake done in "
            f"{(time.perf_counter() - t_dl) * 1000:.0f}ms ({len(raw)} bytes)"
        )

        pil = Image.open(io.BytesIO(raw)).convert("RGB")
        arr = np.array(pil)
        height, width = arr.shape[:2]
        # No EXIF f_px on most web uploads; default to ~62° FOV (phone main lens).
        f_px = float(width) * 0.9
        log.info(
            f"[{request_id}] input: {width}x{height}, f_px={f_px:.1f}"
        )

        t_inf = time.perf_counter()
        gaussians = self._run_inference(arr, f_px)
        inference_ms = (time.perf_counter() - t_inf) * 1000
        log.info(
            f"[{request_id}] inference: predict_image done in "
            f"{inference_ms:.0f}ms"
        )

        t_pack = time.perf_counter()
        splat_bytes, gaussian_count, pos_np, alpha_np = gaussians_to_splat_bytes(
            gaussians
        )
        camera_eye, camera_fwd = auto_frame_camera(pos_np, alpha_np)
        log.info(
            f"[{request_id}] gaussians→splat + auto-frame done in "
            f"{(time.perf_counter() - t_pack) * 1000:.0f}ms; "
            f"splat_size={len(splat_bytes) / (1024 * 1024):.1f} MB "
            f"({gaussian_count} gaussians)"
        )

        t_up = time.perf_counter()
        result_url = upload_to_s3(
            data_bytes=splat_bytes,
            bucket=image_bucket,
            folder="sharp_results",
            extension="splat",
        )
        log.info(
            f"[{request_id}] upload: s3 put done in "
            f"{(time.perf_counter() - t_up) * 1000:.0f}ms; url={result_url}"
        )

        video_url = self._maybe_render_video(gaussians, image_bucket, request_id)

        total_ms = (time.perf_counter() - t0) * 1000
        log.info(
            f"[{request_id}] inference: done in {total_ms:.0f}ms "
            f"(inference={inference_ms:.0f}ms)"
        )

        return {
            "result_url": result_url,
            "video_url": video_url,
            "splat_size_bytes": len(splat_bytes),
            "gaussian_count": gaussian_count,
            "camera_eye": camera_eye,
            "camera_fwd": camera_fwd,
        }

    def _maybe_render_video(
        self,
        gaussians: Any,
        image_bucket: str,
        request_id: str,
    ) -> str | None:
        """Render the wobble-preview MP4 + upload, or no-op if RENDER_VIDEO is off."""

        if not RENDER_VIDEO:
            return None

        from common.sharp_video import render_wobble_mp4

        t_video = time.perf_counter()
        mp4_bytes = render_wobble_mp4(gaussians)
        log.info(
            f"[{request_id}] video: render done in "
            f"{(time.perf_counter() - t_video) * 1000:.0f}ms "
            f"({len(mp4_bytes) / 1024:.0f} KB)"
        )

        t_video_up = time.perf_counter()
        video_url = upload_to_s3(
            data_bytes=mp4_bytes,
            bucket=image_bucket,
            folder="sharp_results",
            extension="mp4",
        )
        log.info(
            f"[{request_id}] video: s3 put done in "
            f"{(time.perf_counter() - t_video_up) * 1000:.0f}ms; "
            f"url={video_url}"
        )
        return video_url

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


@app.function(image=sharp_thin_image, timeout=120)
@modal.fastapi_endpoint(method="POST", requires_proxy_auth=True)
def submit(payload: dict[str, Any]) -> dict[str, Any]:
    """Kick off inference asynchronously; client polls /poll with the call_id."""

    request_id = uuid.uuid4().hex[:8]
    image_bucket = payload.get("image_bucket")
    image_key = payload.get("image_key")
    log.info(
        f"[{request_id}] submit: received; bucket={image_bucket} key={image_key}"
    )

    if not image_bucket or not image_key:
        log.warning(f"[{request_id}] submit: missing image_bucket or image_key")
        return {"error": "image_bucket and image_key are required"}

    call = SharpInference().generate.spawn(
        image_bucket=image_bucket,
        image_key=image_key,
        request_id=request_id,
    )
    log.info(f"[{request_id}] submit: spawned call_id={call.object_id}")
    return {"call_id": call.object_id, "request_id": request_id}


@app.function(image=sharp_thin_image, timeout=120)
@modal.fastapi_endpoint(method="POST", requires_proxy_auth=True)
def poll(payload: dict[str, Any]) -> dict[str, Any]:
    """Non-blocking status check; returns running / done / failed / expired."""

    return poll_function_call(payload.get("call_id"), log)
