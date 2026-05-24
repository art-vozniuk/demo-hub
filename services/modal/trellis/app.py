"""Modal app: Microsoft TRELLIS.2 single-image → textured GLB mesh on GPU.

Same shape as sharp/app.py: download the source image from S3, run the
TRELLIS.2 image-to-3D pipeline, export a PBR-textured .glb, upload it
back to S3, and return only the result URL. Two HTTP endpoints to dodge
Modal's ~60s sync gateway cap:
  POST /submit {image_bucket, image_key} → {call_id, request_id}
  POST /poll   {call_id}                 → {status: ..., ...}
Deploy / preload via services/modal/trellis/{deploy,preload}.py.

NOTE: the image below builds TRELLIS.2's custom CUDA extensions
(O-Voxel, FlexGEMM, CuMesh, nvdiffrast, nvdiffrec). That build is
expected to need a few iterations to go green — tune the steps here and
redeploy; nothing else in the stack depends on the exact build recipe.
"""

from __future__ import annotations

import io
import os
import tempfile
import time
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


MODEL_REPO = "microsoft/TRELLIS.2-4B"
MODEL_LOCAL_DIR = f"{MODEL_DIR}/trellis2-4b"

# Full-quality render resolution. 512 fits an A10G (24GB); see GPU note
# on the @app.cls below if this ever OOMs.
RENDER_RESOLUTION = 512


log = configure_logging("trellis")
app, volume = make_app("demo-hub-trellis", "trellis-models")


# TRELLIS.2 ships custom CUDA extensions, so unlike sharp/flux we need a
# CUDA *devel* base (nvcc + headers) to compile them. torch/CUDA versions
# follow the microsoft/TRELLIS.2 README; bump here if the build complains
# about an ABI mismatch.
CUDA_TAG = "12.4.1"
TRELLIS_SRC = "/opt/TRELLIS.2"

trellis_image = (
    modal.Image.from_registry(
        f"nvidia/cuda:{CUDA_TAG}-devel-ubuntu22.04", add_python="3.11"
    )
    .apt_install(
        "git",
        "build-essential",
        "ninja-build",
        "cmake",
        # GL/EGL stack for nvdiffrast headless rendering.
        "libgl1",
        "libglib2.0-0",
        "libegl1",
        "libgles2-mesa-dev",
        "libglvnd-dev",
        "pkg-config",
    )
    .pip_install(
        # torch/torchvision pinned together — CUDA ABI mismatch hurts the
        # extension builds below. cu124 wheels match the devel base.
        "torch==2.5.1",
        "torchvision==0.20.1",
        "numpy",
        "Pillow==11.0.0",
        "transformers",
        "accelerate",
        "safetensors",
        "huggingface-hub[hf-transfer]>=0.34.0",
        "trimesh",
        "xatlas",
        "pymeshlab",
        "fastapi[standard]==0.115.6",
        "pydantic==2.10.3",
        "boto3==1.35.92",
        extra_options="--extra-index-url https://download.pytorch.org/whl/cu124",
    )
    .env(
        {
            "HF_HUB_ENABLE_HF_TRANSFER": "1",
            "HF_HOME": "/root/.cache/huggingface",
            "TRANSFORMERS_OFFLINE": "0",
            # TRELLIS runtime knobs — native spconv algo is the most
            # portable; attention backend is left to the lib default.
            "SPCONV_ALGO": "native",
            # nvdiffrast needs an EGL device to render off-screen.
            "PYOPENGL_PLATFORM": "egl",
        }
    )
    # Clone with submodules, then build each custom extension. Order
    # matters: o_voxel and the GEMM/mesh kernels first, rasterizers last.
    .run_commands(
        f"git clone --recursive https://github.com/microsoft/TRELLIS.2.git {TRELLIS_SRC}",
        f"pip install {TRELLIS_SRC}/o_voxel --no-build-isolation",
        f"pip install {TRELLIS_SRC}/extensions/flexgemm --no-build-isolation",
        f"pip install {TRELLIS_SRC}/extensions/cumesh --no-build-isolation",
        "pip install git+https://github.com/NVlabs/nvdiffrast.git --no-build-isolation",
        "pip install git+https://github.com/NVlabs/nvdiffrec.git --no-build-isolation",
        f"pip install {TRELLIS_SRC} --no-build-isolation",
        gpu="A10G",
    )
    # Modal no longer auto-mounts sibling files; ship common.lib explicitly.
    .add_local_python_source("common.lib")
)


# submit/poll only spawn / inspect a FunctionCall — no torch needed. A
# thin image keeps their cold-start small. Same pattern as sharp/app.py.
trellis_thin_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "fastapi[standard]==0.115.6",
        "pydantic==2.10.3",
    )
    .add_local_python_source("common.lib")
)


with trellis_image.imports():
    import o_voxel
    from PIL import Image
    from trellis.pipelines import Trellis2ImageTo3DPipeline


@app.function(
    image=trellis_image,
    volumes={MODEL_DIR: volume},
    timeout=60 * 60,
    secrets=[modal.Secret.from_name("huggingface", required_keys=[])],
)
def preload_weights() -> str:
    """Download TRELLIS.2-4B into the persistent volume.

    Run once: `python services/modal/trellis/preload.py`. Re-running is a
    no-op when files are already up to date.
    """

    from huggingface_hub import snapshot_download

    log.info(f"preload: starting; repo={MODEL_REPO} -> {MODEL_LOCAL_DIR}")
    t0 = time.perf_counter()
    os.makedirs(MODEL_LOCAL_DIR, exist_ok=True)

    has_token = bool(os.environ.get("HF_TOKEN"))
    log.info(f"preload: hf_token_present={has_token}")

    snapshot_download(
        repo_id=MODEL_REPO,
        local_dir=MODEL_LOCAL_DIR,
        token=os.environ.get("HF_TOKEN"),
        max_workers=8,
    )
    download_ms = (time.perf_counter() - t0) * 1000
    log.info(f"preload: snapshot_download finished in {download_ms:.0f}ms")

    t1 = time.perf_counter()
    volume.commit()
    commit_ms = (time.perf_counter() - t1) * 1000
    total_ms = (time.perf_counter() - t0) * 1000
    log.info(
        f"preload: volume.commit took {commit_ms:.0f}ms "
        f"(total {total_ms:.0f}ms); weights at {MODEL_LOCAL_DIR}"
    )

    return MODEL_LOCAL_DIR


# GPU note: 512-res TRELLIS.2 fits an A10G (24GB). If a real input OOMs,
# do NOT drop the resolution/quality — bump the tier to gpu="L40S" (48GB).
@app.cls(
    image=trellis_image,
    gpu="A10G",
    volumes={MODEL_DIR: volume},
    scaledown_window=10,
    timeout=600,
    enable_memory_snapshot=True,
    secrets=[modal.Secret.from_name("supabase-s3")],
    # min_containers=1,
)
@modal.concurrent(max_inputs=1)
class TrellisInference:
    @modal.enter(snap=True)
    def load_to_cpu(self) -> None:
        """Snapshot hook: runs ONCE on a CPU-only container before Modal
        captures the memory snapshot. Loads pipeline weights from the
        volume into RAM so future cold starts skip the disk read."""

        log.info(
            "snapshot-load: load_to_cpu() begin; runs once during snapshot "
            "creation on a CPU container (no GPU attached here yet)"
        )
        t0 = time.perf_counter()

        self.pipe = Trellis2ImageTo3DPipeline.from_pretrained(MODEL_LOCAL_DIR)
        from_pretrained_ms = (time.perf_counter() - t0) * 1000
        log.info(
            f"snapshot-load: from_pretrained({MODEL_LOCAL_DIR}) "
            f"finished in {from_pretrained_ms:.0f}ms; "
            "Modal will snapshot RAM after this returns"
        )

    @modal.enter(snap=False)
    def move_to_gpu(self) -> None:
        """Post-restore hook: runs on every cold start AFTER snapshot
        restore (or fresh start), with the GPU now attached. Shuttles
        weights to CUDA, then runs a tiny warmup inference so the custom
        CUDA kernels JIT-compile now instead of on the first real request."""

        log.info(
            "post-restore: move_to_gpu() begin; runs after each container "
            "start, with the GPU now attached"
        )
        t0 = time.perf_counter()
        self.pipe.cuda()
        to_cuda_ms = (time.perf_counter() - t0) * 1000
        log.info(f"post-restore: pipe.cuda() finished in {to_cuda_ms:.0f}ms")

        # Warmup: a throwaway run on a tiny image forces the extension
        # kernels to compile up front. Best-effort — never fail the start.
        try:
            t_warm = time.perf_counter()
            dummy = Image.new("RGB", (64, 64), (127, 127, 127))
            self.pipe.run(dummy)
            warm_ms = (time.perf_counter() - t_warm) * 1000
            log.info(f"post-restore: warmup inference done in {warm_ms:.0f}ms")
        except Exception as e:
            log.warning(f"post-restore: warmup inference failed (non-fatal): {e!r}")

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

        image = Image.open(io.BytesIO(raw)).convert("RGB")
        log.info(
            f"[{request_id}] inference: decoded input "
            f"{image.width}x{image.height}, {len(raw)} bytes"
        )

        t_inf = time.perf_counter()
        mesh = self.pipe.run(image)[0]
        inference_ms = (time.perf_counter() - t_inf) * 1000
        log.info(
            f"[{request_id}] inference: pipe.run(...) returned in {inference_ms:.0f}ms"
        )

        # Export a PBR-textured GLB at full render resolution.
        t_exp = time.perf_counter()
        glb = o_voxel.postprocess.to_glb(mesh, texture_size=RENDER_RESOLUTION)
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "out.glb")
            glb.export(out_path)
            with open(out_path, "rb") as f:
                glb_bytes = f.read()
        export_ms = (time.perf_counter() - t_exp) * 1000
        log.info(
            f"[{request_id}] export: to_glb done in {export_ms:.0f}ms; "
            f"glb_size={len(glb_bytes) / (1024 * 1024):.1f} MB"
        )

        t_up = time.perf_counter()
        result_url = upload_to_s3(
            data_bytes=glb_bytes,
            bucket=image_bucket,
            folder="trellis_results",
            extension="glb",
        )
        upload_ms = (time.perf_counter() - t_up) * 1000

        total_ms = (time.perf_counter() - t0) * 1000
        log.info(
            f"[{request_id}] inference: done in {total_ms:.0f}ms "
            f"(inference={inference_ms:.0f}ms export={export_ms:.0f}ms "
            f"upload={upload_ms:.0f}ms); url={result_url}"
        )

        return {
            "result_url": result_url,
            "glb_size_bytes": len(glb_bytes),
        }


@app.function(image=trellis_thin_image, timeout=120)
@modal.fastapi_endpoint(method="POST", requires_proxy_auth=True)
def submit(payload: dict[str, Any]) -> dict[str, Any]:
    """Kick off inference asynchronously; client polls /poll with the call_id."""

    request_id = uuid.uuid4().hex[:8]
    image_bucket = payload.get("image_bucket")
    image_key = payload.get("image_key")
    log.info(f"[{request_id}] submit: received; bucket={image_bucket} key={image_key}")

    if not image_bucket or not image_key:
        log.warning(f"[{request_id}] submit: missing image_bucket or image_key")
        return {"error": "image_bucket and image_key are required"}

    call = TrellisInference().generate.spawn(
        image_bucket=image_bucket,
        image_key=image_key,
        request_id=request_id,
    )
    log.info(f"[{request_id}] submit: spawned call_id={call.object_id}")
    return {"call_id": call.object_id, "request_id": request_id}


@app.function(image=trellis_thin_image, timeout=120)
@modal.fastapi_endpoint(method="POST", requires_proxy_auth=True)
def poll(payload: dict[str, Any]) -> dict[str, Any]:
    """Non-blocking status check; returns running / done / failed / expired."""

    return poll_function_call(payload.get("call_id"), log)
