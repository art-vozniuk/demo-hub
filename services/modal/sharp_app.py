"""Modal app: Apple ml-sharp single-image → 3DGS on A10G.

Deploy:
    modal deploy services/modal/sharp_app.py

Preload weights into the volume (one-shot):
    modal run services/modal/sharp_app.py::preload_weights

Mirrors services/modal/app.py (FLUX generative editing) — same A10G +
memory-snapshot + FastAPI-endpoint pattern, swapped pipeline.

Output schema (returned from the HTTP endpoint):

    {
        "splat_b64": str,        # base64 of 32-byte-per-gaussian .splat blob
        "gaussian_count": int,   # number of gaussians in the splat
        "camera_eye": [x, y, z], # auto-framed initial camera position
        "camera_fwd": [x, y, z], # camera forward direction
    }
"""

from __future__ import annotations

import base64
import io
import logging
import os
import tempfile
import time
import urllib.request
import uuid
from typing import Any

import modal


APP_NAME = "demo-hub-sharp"
VOLUME_NAME = "sharp-models"
MODEL_DIR = "/models"
CHECKPOINT_URL = "https://ml-site.cdn-apple.com/models/sharp/sharp_2572gikvuh.pt"
CHECKPOINT_LOCAL_PATH = f"{MODEL_DIR}/sharp_2572gikvuh.pt"

# Hard cap on splat size to stay under Supabase Storage's 50 MB-per-object
# limit (matches services/gs-training-local/pipeline/compress_splat.py).
# At 32 bytes/gaussian that's ~1.5M gaussians.
MAX_SPLAT_BYTES = 50 * 1024 * 1024
MAX_GAUSSIANS = MAX_SPLAT_BYTES // 32

# Constant SH basis Y_0^0 — used by 3DGS PLYs to encode the DC RGB term.
SH_C0 = 0.28209479177387814


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("sharp")


app = modal.App(APP_NAME)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)


# Apple's ml-sharp recommends Python 3.13 (per its README). Modal supports it,
# and torch 2.5.x has 3.13 wheels.
sharp_image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("git", "libgl1", "libglib2.0-0")
    .pip_install(
        "torch==2.5.1",
        "torchvision==0.20.1",
        "numpy",
        "Pillow==11.0.0",
        "plyfile",
        "click",
        "fastapi[standard]==0.115.6",
        "pydantic==2.10.3",
        # ml-sharp is published only on GitHub; no PyPI release. Pull from
        # main — pin to a commit once Apple cuts a tagged release.
        "git+https://github.com/apple/ml-sharp.git",
    )
)


with sharp_image.imports():
    import numpy as np
    import torch
    from PIL import Image, ImageOps
    from plyfile import PlyData
    from sharp.models import PredictorParams, create_predictor
    from sharp.utils.gaussians import save_ply


def _ensure_checkpoint() -> str:
    """Download the SHARP checkpoint into the Modal volume if not present.

    Idempotent: subsequent calls return the cached path. Called from both
    `preload_weights` (explicit one-shot setup) and the `@modal.enter` hook
    (in case preload was skipped — keeps cold starts self-healing).
    """

    if os.path.exists(CHECKPOINT_LOCAL_PATH):
        log.info(f"checkpoint cached at {CHECKPOINT_LOCAL_PATH}")
        return CHECKPOINT_LOCAL_PATH

    log.info(f"downloading checkpoint from {CHECKPOINT_URL} -> {CHECKPOINT_LOCAL_PATH}")
    os.makedirs(MODEL_DIR, exist_ok=True)
    t0 = time.perf_counter()
    # Stream to a sibling .tmp file then rename — partial downloads don't
    # leave a half-broken file in the cache on container kill.
    tmp = CHECKPOINT_LOCAL_PATH + ".tmp"
    urllib.request.urlretrieve(CHECKPOINT_URL, tmp)
    os.replace(tmp, CHECKPOINT_LOCAL_PATH)
    size_mb = os.path.getsize(CHECKPOINT_LOCAL_PATH) / (1024 * 1024)
    log.info(
        f"checkpoint downloaded ({size_mb:.1f} MB) "
        f"in {(time.perf_counter() - t0):.1f}s"
    )
    return CHECKPOINT_LOCAL_PATH


@app.function(
    image=sharp_image,
    volumes={MODEL_DIR: volume},
    timeout=60 * 30,
    cpu=4.0,
    memory=8192,
)
def preload_weights() -> str:
    """Download the SHARP checkpoint into the persistent volume.

    Run once: `modal run services/modal/sharp_app.py::preload_weights`.
    Re-running is a no-op when the file is already present.
    """

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
        """Snapshot hook: load predictor weights into CPU RAM once, before
        Modal freezes the memory snapshot. Future cold starts skip the disk
        read — the RAM image is restored straight from the snapshot."""

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
        """Post-restore hook: weights are already in RAM (from snapshot or
        from the load_to_cpu hook on first start), just shuttle to GPU."""

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
    ) -> dict[str, Any]:
        log.info(f"[{request_id}] inference: start")
        t0 = time.perf_counter()

        # 1. Decode + orient input
        raw = base64.b64decode(image_b64)
        pil = Image.open(io.BytesIO(raw))
        # Bake phone-portrait EXIF rotation in — SHARP's preprocessing drops
        # it, so without this a portrait photo arrives at the model sideways.
        pil = ImageOps.exif_transpose(pil)
        if pil.mode != "RGB":
            pil = pil.convert("RGB")
        arr = np.array(pil)
        height, width = arr.shape[:2]
        log.info(f"[{request_id}] input: {width}x{height}, {len(raw)} bytes")

        # SHARP needs a focal length in pixels. EXIF on web-uploaded photos
        # is often stripped, so use a sensible default for phone-camera FOV
        # (~62° horizontal). Picking too small under-projects the scene
        # (everything bunches near origin); too large blows the scene up.
        # 0.9 * width is a reasonable midpoint for "typical phone photo".
        f_px = float(width) * 0.9

        # 2. Inference
        t_inf = time.perf_counter()
        gaussians = self._run_inference(arr, f_px)
        inference_ms = (time.perf_counter() - t_inf) * 1000
        log.info(
            f"[{request_id}] inference: predict_image done in "
            f"{inference_ms:.0f}ms"
        )

        # 3. Save to standard 3DGS PLY (handles linearRGB→sRGB +
        # opacity-to-logit conversions for us), then re-pack into our
        # 32-byte-per-gaussian .splat layout.
        with tempfile.TemporaryDirectory() as td:
            ply_path = f"{td}/scene.ply"
            t_save = time.perf_counter()
            save_ply(gaussians, f_px, (height, width), ply_path)
            log.info(
                f"[{request_id}] save_ply done in "
                f"{(time.perf_counter() - t_save) * 1000:.0f}ms; "
                f"size={os.path.getsize(ply_path) / (1024 * 1024):.1f} MB"
            )

            t_pack = time.perf_counter()
            splat_bytes, gaussian_count = _ply_to_splat_bytes(ply_path)
            pack_ms = (time.perf_counter() - t_pack) * 1000
            log.info(
                f"[{request_id}] pack splat done in {pack_ms:.0f}ms; "
                f"{gaussian_count} gaussians, "
                f"{len(splat_bytes) / (1024 * 1024):.1f} MB"
            )

        # 4. Auto-frame initial camera from gaussian positions. SHARP
        # follows OpenCV convention with scene centered around (0, 0, +z);
        # placing the eye at -2.5*radius behind the centroid along the
        # depth axis gives a reasonable default framing for ad-hoc views.
        eye, fwd = _auto_frame_camera(splat_bytes, gaussian_count)

        total_ms = (time.perf_counter() - t0) * 1000
        log.info(
            f"[{request_id}] inference: done in {total_ms:.0f}ms "
            f"(inference={inference_ms:.0f}ms)"
        )

        return {
            "splat_b64": base64.b64encode(splat_bytes).decode("ascii"),
            "gaussian_count": gaussian_count,
            "camera_eye": eye,
            "camera_fwd": fwd,
        }

    @torch.no_grad()
    def _run_inference(self, image: "np.ndarray", f_px: float) -> Any:
        """Reproduces sharp.cli.predict.predict_image() inline.

        Inlined instead of imported to avoid a click-CLI dependency at
        runtime — SHARP's predict_image isn't a publicly committed API
        (lives under cli/), so calling it directly couples us to internal
        layout. The preprocessing/postprocessing pipeline below mirrors
        upstream as of the pinned ml-sharp main; revisit when Apple ships
        a stable `sharp` Python API.
        """

        import torch.nn.functional as F  # noqa: N812
        from sharp.utils.gaussians import unproject_gaussians

        device = torch.device("cuda")
        internal_shape = (1536, 1536)

        image_pt = (
            torch.from_numpy(image.copy()).float().to(device).permute(2, 0, 1) / 255.0
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
            gaussians_ndc, torch.eye(4).to(device), intrinsics_resized, internal_shape
        )


def _ply_to_splat_bytes(ply_path: str) -> tuple[bytes, int]:
    """Read a 3DGS-standard PLY and pack into our 32-byte-per-gaussian layout.

    Math mirrors services/gs-training-local/pipeline/compress_splat.py —
    inlined here so this Modal app stays self-contained without needing
    to mount the gs-training-local package. Keep the two in sync.

    Output struct (matches antimatter15/splat + mkkellogg/GaussianSplats3D):

        struct Gaussian {                  // 32 bytes
          float position[3];               // 12
          float scales[3];                 // 12 (already exp'd)
          uint8 rgba[4];                   //  4 (SH DC → RGB; sigmoid opacity)
          uint8 rotation[4];               //  4 ([-1,1] → [0,255])
        };

    If the result would exceed Supabase's 50 MB file limit, drop the
    lowest-opacity gaussians until we fit. Quality loss is graceful —
    transparent splats contribute least to the rendered image.
    """

    splat_dtype = np.dtype([
        ("xyz",    np.float32, 3),
        ("scales", np.float32, 3),
        ("rgba",   np.uint8,   4),
        ("rot",    np.uint8,   4),
    ])

    plydata = PlyData.read(ply_path)
    v = plydata["vertex"].data
    n = len(v)

    xyz = np.stack([v["x"], v["y"], v["z"]], axis=-1).astype(np.float32)
    scales = np.exp(
        np.stack(
            [v["scale_0"], v["scale_1"], v["scale_2"]], axis=-1
        ).astype(np.float32)
    )
    rot = np.stack(
        [v["rot_0"], v["rot_1"], v["rot_2"], v["rot_3"]], axis=-1
    ).astype(np.float32)
    rot_norm = np.linalg.norm(rot, axis=-1, keepdims=True)
    rot_norm[rot_norm == 0] = 1.0
    rot /= rot_norm
    rot_u8 = np.clip(np.round((rot * 0.5 + 0.5) * 255.0), 0, 255).astype(np.uint8)

    dc = np.stack(
        [v["f_dc_0"], v["f_dc_1"], v["f_dc_2"]], axis=-1
    ).astype(np.float32)
    rgb = np.clip(0.5 + SH_C0 * dc, 0.0, 1.0)
    opacity = 1.0 / (1.0 + np.exp(-v["opacity"].astype(np.float32)))
    rgba_u8 = np.empty((n, 4), dtype=np.uint8)
    rgba_u8[:, :3] = np.round(rgb * 255.0).astype(np.uint8)
    rgba_u8[:, 3] = np.clip(np.round(opacity * 255.0), 0, 255).astype(np.uint8)

    # Cap at MAX_GAUSSIANS by keeping the highest-opacity ones. With
    # SHARP's 1536×1536 internal resolution the raw output can hit
    # ~2.4M gaussians; we need to come in under Supabase's per-object
    # limit before the upload step.
    if n > MAX_GAUSSIANS:
        log.warning(
            f"trimming {n} gaussians → {MAX_GAUSSIANS} by opacity to fit "
            f"under {MAX_SPLAT_BYTES} bytes"
        )
        # argsort ascending; take the top MAX_GAUSSIANS by opacity
        order = np.argsort(opacity)[-MAX_GAUSSIANS:]
        xyz = xyz[order]
        scales = scales[order]
        rgba_u8 = rgba_u8[order]
        rot_u8 = rot_u8[order]
        n = MAX_GAUSSIANS

    arr = np.empty(n, dtype=splat_dtype)
    arr["xyz"] = xyz
    arr["scales"] = scales
    arr["rgba"] = rgba_u8
    arr["rot"] = rot_u8

    return arr.tobytes(), n


def _auto_frame_camera(
    splat_bytes: bytes, gaussian_count: int
) -> tuple[list[float], list[float]]:
    """Pick an initial (eye, fwd) so the user sees something on first load.

    SHARP centers the reconstructed scene around (0, 0, +z) in OpenCV
    convention. We pull the per-gaussian xyz back out of the packed splat
    blob, compute centroid + radius, then place the camera one scene-
    radius behind the centroid along -z, looking toward +z. Good enough
    for a single-image demo where there's no canonical "front" of the
    scene to align to.
    """

    if gaussian_count == 0:
        return [0.0, 0.0, 0.0], [0.0, 0.0, 1.0]

    # Re-interpret the first 12 bytes of each 32-byte record as xyz floats
    # without copying the whole blob — we already paid for one round of
    # packing, no point doing another.
    raw = np.frombuffer(splat_bytes, dtype=np.uint8).reshape(gaussian_count, 32)
    xyz = raw[:, :12].view(np.float32).reshape(gaussian_count, 3)

    centroid = xyz.mean(axis=0)
    # Use the max-axis half-extent rather than full distance — quieter to
    # outliers (a single far-away gaussian doesn't blow the framing).
    half_extent = np.abs(xyz - centroid).max(axis=0)
    radius = float(np.linalg.norm(half_extent))
    if radius < 1e-3:
        radius = 1.0  # degenerate scene; back the camera off by a unit

    # 2.5×radius pull-back along -z; clamp so we never end up at the
    # origin or behind the camera plane.
    pullback = max(2.5 * radius, 1.0)
    eye = [
        float(centroid[0]),
        float(centroid[1]),
        float(centroid[2] - pullback),
    ]
    fwd = [0.0, 0.0, 1.0]
    log.info(
        f"auto-frame: centroid={centroid.tolist()} radius={radius:.3f} "
        f"eye={eye} fwd={fwd}"
    )
    return eye, fwd


@app.function(
    image=sharp_image,
    timeout=600,
)
@modal.fastapi_endpoint(method="POST", requires_proxy_auth=True)
def generate(payload: dict[str, Any]) -> dict[str, Any]:
    """Public HTTP entry point. Gated by Modal proxy-auth — Modal validates
    incoming Modal-Key/Modal-Secret headers against tokens issued in the
    dashboard at /settings/proxy-auth-tokens."""

    request_id = uuid.uuid4().hex[:8]
    t0 = time.perf_counter()

    image_b64 = payload.get("image_b64")
    log.info(
        f"[{request_id}] endpoint: POST received; "
        f"image_b64_len={len(image_b64) if image_b64 else 0}"
    )

    if not image_b64:
        log.warning(f"[{request_id}] endpoint: rejecting; missing image_b64")
        return {"error": "image_b64 is required"}

    inference = SharpInference()
    result = inference.generate.remote(
        request_id=request_id,
        image_b64=image_b64,
    )

    total_ms = (time.perf_counter() - t0) * 1000
    log.info(
        f"[{request_id}] endpoint: done; total_ms={total_ms:.0f} "
        f"gaussians={result.get('gaussian_count') if isinstance(result, dict) else 0}"
    )
    return result
