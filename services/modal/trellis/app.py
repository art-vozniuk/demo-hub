"""Modal app: TRELLIS.2 single-image → textured GLB mesh on GPU.

Two HTTP endpoints (submit/poll) to dodge Modal's ~60s sync gateway cap.
Deploy / preload via services/modal/trellis/{deploy,preload}.py.
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
# HF cache lives on the volume so transitive downloads survive scaledowns.
HF_CACHE_DIR = f"{MODEL_DIR}/hf_cache"
# Upstream configs reference dinov3 (Meta, closed) and RMBG-2.0 (Bria,
# gated). camenduru mirrors both as open repos; preload patches the
# config json to swap the names.
HF_REPO_REWRITES = {
    "facebook/dinov3-vitl16-pretrain-lvd1689m": "camenduru/dinov3-vitl16-pretrain-lvd1689m",
    "briaai/RMBG-2.0": "camenduru/RMBG-2.0",
}
HF_AUX_REPOS = [
    "microsoft/TRELLIS-image-large",
    *HF_REPO_REWRITES.values(),
]

# Texture bake size. 4096 is upstream's default but nvdiffrast rasterization
# scales O(N²) — on A10G it stalls past 10 min. 2048 keeps detail without that.
TEXTURE_RESOLUTION = 2048

# Sampler steps when the request doesn't override it. 12 is upstream default
# (high quality), 4 is the minimum that still gives a coherent mesh.
DEFAULT_SAMPLER_STEPS = 8
ALLOWED_SAMPLER_STEPS = {4, 8, 12}


log = configure_logging("trellis")
app, volume = make_app("demo-hub-trellis", "trellis-models")


# Devel base needed for nvcc + headers to compile TRELLIS.2's CUDA exts.
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
        # torch 2.6 ships triton ≥ 3.2 required by FlexGEMM; cu124 wheels
        # match the devel base above.
        "torch==2.6.0",
        "torchvision==0.21.0",
        "numpy",
        "Pillow==11.0.0",
        # 4.57.x is the latest 4.x: 5.x removed attrs BiRefNet relies on,
        # 4.56+ added DINOv3ViTModel.
        "transformers==4.57.6",
        "accelerate",
        "safetensors",
        "huggingface-hub[hf-transfer]>=0.34.0",
        "trimesh",
        "xatlas",
        "pymeshlab",
        # Build tooling reachable from --no-build-isolation ext installs.
        "wheel",
        "setuptools>=64",
        "plyfile",
        # TRELLIS.2 --basic deps from upstream setup.sh, minus train/UI bits.
        "easydict",
        "ninja",
        "tqdm",
        "imageio",
        "imageio-ffmpeg",
        "opencv-python-headless",
        "kornia",
        "timm",
        "lpips",
        "zstandard",
        "fastapi[standard]==0.115.6",
        "pydantic==2.10.3",
        "boto3==1.35.92",
        extra_options="--extra-index-url https://download.pytorch.org/whl/cu124",
    )
    .env(
        {
            "HF_HUB_ENABLE_HF_TRANSFER": "1",
            "HF_HOME": HF_CACHE_DIR,
            "TRANSFORMERS_OFFLINE": "0",
            # Portable spconv backend.
            "SPCONV_ALGO": "native",
            # Off-screen rendering for nvdiffrast.
            "PYOPENGL_PLATFORM": "egl",
            # trellis2 has no setup.py; import from a checkout.
            "PYTHONPATH": TRELLIS_SRC,
            "OPENCV_IO_ENABLE_OPENEXR": "1",
            # Force g++ for ext builds — Modal's add_python uses clang,
            # which trips PyTorch's g++-built ABI.
            "CC": "gcc",
            "CXX": "g++",
            "LDSHARED": "g++ -shared",
        }
    )
    # FlexGEMM and CuMesh first: o-voxel pyproject lists them as git+
    # runtime deps, pre-installing lets o-voxel pass --no-deps.
    .run_commands(
        f"git clone --recursive https://github.com/microsoft/TRELLIS.2.git {TRELLIS_SRC}",
        "git clone --recursive https://github.com/JeffreyXiang/FlexGEMM.git /tmp/extensions/FlexGEMM",
        "pip install /tmp/extensions/FlexGEMM --no-build-isolation",
        "git clone --recursive https://github.com/JeffreyXiang/CuMesh.git /tmp/extensions/CuMesh",
        "pip install /tmp/extensions/CuMesh --no-build-isolation",
        # Folder is o-voxel (hyphen), Python package is o_voxel.
        f"pip install {TRELLIS_SRC}/o-voxel --no-build-isolation --no-deps",
        "git clone -b v0.4.0 https://github.com/NVlabs/nvdiffrast.git /tmp/extensions/nvdiffrast",
        "pip install /tmp/extensions/nvdiffrast --no-build-isolation",
        "git clone -b renderutils https://github.com/JeffreyXiang/nvdiffrec.git /tmp/extensions/nvdiffrec",
        "pip install /tmp/extensions/nvdiffrec --no-build-isolation",
        "pip install flash-attn==2.7.3 --no-build-isolation",
        "pip install git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8",
        gpu="A10G",
    )
    .add_local_python_source("common.lib")
)


# Thin image for submit/poll — no torch, fast cold-start.
trellis_thin_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "fastapi[standard]==0.115.6",
        "pydantic==2.10.3",
    )
    .add_local_python_source("common.lib")
)


# o_voxel + trellis2 require a GPU at import time (flex_gemm triton
# autotune). Import them lazily inside generate(), not at module level.


@app.function(
    image=trellis_image,
    volumes={MODEL_DIR: volume},
    timeout=60 * 60,
    secrets=[modal.Secret.from_name("huggingface", required_keys=[])],
)
def preload_weights() -> str:
    """Download TRELLIS.2-4B + transitive HF deps into the volume.

    Idempotent; runs via services/modal/trellis/preload.py.
    """

    from huggingface_hub import snapshot_download

    log.info(f"preload: starting; main_repo={MODEL_REPO} -> {MODEL_LOCAL_DIR}")
    t0 = time.perf_counter()
    os.makedirs(MODEL_LOCAL_DIR, exist_ok=True)
    os.makedirs(HF_CACHE_DIR, exist_ok=True)

    hf_token = os.environ.get("HF_TOKEN")
    log.info(f"preload: hf_token_present={bool(hf_token)}")

    snapshot_download(
        repo_id=MODEL_REPO,
        local_dir=MODEL_LOCAL_DIR,
        token=hf_token,
        max_workers=8,
    )
    log.info(
        f"preload: main repo done in {(time.perf_counter() - t0) * 1000:.0f}ms"
    )

    # Swap gated repo names in the pipeline configs to their mirrors.
    import glob

    rewrites = 0
    for cfg in glob.glob(f"{MODEL_LOCAL_DIR}/*pipeline.json"):
        with open(cfg, "r") as f:
            src = f.read()
        new = src
        for orig, mirror in HF_REPO_REWRITES.items():
            new = new.replace(orig, mirror)
        if new != src:
            with open(cfg, "w") as f:
                f.write(new)
            rewrites += 1
            log.info(f"preload: rewrote gated repo paths in {cfg}")
    log.info(f"preload: patched {rewrites} pipeline config(s)")

    # Preload transitive HF deps so cold inference skips the network.
    for repo in HF_AUX_REPOS:
        t_aux = time.perf_counter()
        log.info(f"preload: aux repo {repo} -> {HF_CACHE_DIR}")
        try:
            snapshot_download(
                repo_id=repo,
                cache_dir=HF_CACHE_DIR,
                token=hf_token,
                max_workers=8,
            )
            log.info(
                f"preload: aux repo {repo} done in "
                f"{(time.perf_counter() - t_aux) * 1000:.0f}ms"
            )
        except Exception as e:
            # One aux repo failure (e.g. unapproved gated access) shouldn't
            # break the whole preload — runtime cold-start surfaces it too.
            log.error(f"preload: aux repo {repo} FAILED: {e!r}")

    t1 = time.perf_counter()
    volume.commit()
    commit_ms = (time.perf_counter() - t1) * 1000
    total_ms = (time.perf_counter() - t0) * 1000
    log.info(
        f"preload: volume.commit took {commit_ms:.0f}ms "
        f"(total {total_ms:.0f}ms); main weights at {MODEL_LOCAL_DIR}, "
        f"hf cache at {HF_CACHE_DIR}"
    )

    return MODEL_LOCAL_DIR


# A10G (24GB) fits TRELLIS.2 at current settings; bump to L40S on OOM.
@app.cls(
    image=trellis_image,
    gpu="L40S",
    volumes={MODEL_DIR: volume},
    scaledown_window=10,
    timeout=600,
    retries=modal.Retries(max_retries=0),
    # GPU snapshot keeps the GPU attached during snap=True, which is
    # required because flex_gemm/triton init driver state on import.
    enable_memory_snapshot=True,
    experimental_options={"enable_gpu_snapshot": True},
    secrets=[
        modal.Secret.from_name("supabase-s3"),
        # Belt-and-suspenders for HF deps the preload missed.
        modal.Secret.from_name("huggingface", required_keys=[]),
    ],
    # min_containers=1,
)
@modal.concurrent(max_inputs=1)
class TrellisInference:
    @modal.enter(snap=True)
    def load(self) -> None:
        """Load the pipeline + run a warmup pass.

        Errors are stashed on self instead of raising — a raise from an
        enter hook makes Modal restart the container indefinitely (it
        thinks the container couldn't start), so generate() surfaces
        the failure as a normal function error instead.
        """

        self.pipe = None
        self.init_error: BaseException | None = None
        log.info("enter: load() begin on GPU container")
        t0 = time.perf_counter()

        try:
            # Lazy: top-level import would also fail on the CPU containers
            # serving preload_weights / submit / poll.
            from trellis2.pipelines import Trellis2ImageTo3DPipeline

            self.pipe = Trellis2ImageTo3DPipeline.from_pretrained(MODEL_LOCAL_DIR)
            from_pretrained_ms = (time.perf_counter() - t0) * 1000
            log.info(
                f"enter: from_pretrained({MODEL_LOCAL_DIR}) "
                f"finished in {from_pretrained_ms:.0f}ms"
            )

            t_gpu = time.perf_counter()
            self.pipe.cuda()
            to_cuda_ms = (time.perf_counter() - t_gpu) * 1000
            log.info(f"enter: pipe.cuda() finished in {to_cuda_ms:.0f}ms")
        except Exception as e:
            log.exception("enter: pipeline init failed")
            self.init_error = e
            return

        # Warmup with an upstream example image so RMBG actually finds a
        # foreground; a blank dummy returns an empty mask and crashes
        # downstream max(). Forces cumesh + nvdiffrast kernels to JIT
        # before the snapshot is captured.
        try:
            from PIL import Image

            t_warm = time.perf_counter()
            warmup_image_path = f"{TRELLIS_SRC}/assets/example_image/T.png"
            self.pipe.run(Image.open(warmup_image_path).convert("RGB"))
            warm_ms = (time.perf_counter() - t_warm) * 1000
            log.info(f"enter: warmup inference done in {warm_ms:.0f}ms")
        except Exception as e:
            log.warning(f"enter: warmup inference failed (non-fatal): {e!r}")

    @modal.method()
    def generate(
        self,
        image_bucket: str,
        image_key: str,
        request_id: str,
        steps: int | None = None,
    ) -> dict[str, Any]:
        if self.init_error is not None or self.pipe is None:
            raise RuntimeError(
                f"TrellisInference init failed: {self.init_error!r}"
            )

        # Lazy: these modules touch the GPU on import, can't load on CPU.
        import o_voxel
        from PIL import Image

        steps = steps if steps in ALLOWED_SAMPLER_STEPS else DEFAULT_SAMPLER_STEPS
        log.info(f"[{request_id}] inference: start; key={image_key}; steps={steps}")
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
        # All three samplers default from pipeline.json (steps=12); kwargs
        # here override per-request.
        steps_override = {"steps": steps}
        mesh = self.pipe.run(
            image,
            sparse_structure_sampler_params=steps_override,
            shape_slat_sampler_params=steps_override,
            tex_slat_sampler_params=steps_override,
        )[0]
        # nvdiffrast hard limit on face count.
        mesh.simplify(16777216)
        inference_ms = (time.perf_counter() - t_inf) * 1000
        log.info(
            f"[{request_id}] inference: pipe.run(...) returned in {inference_ms:.0f}ms"
        )

        t_exp = time.perf_counter()
        glb = o_voxel.postprocess.to_glb(
            vertices=mesh.vertices,
            faces=mesh.faces,
            attr_volume=mesh.attrs,
            coords=mesh.coords,
            attr_layout=mesh.layout,
            voxel_size=mesh.voxel_size,
            aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
            decimation_target=1000000,
            texture_size=TEXTURE_RESOLUTION,
            remesh=True,
            remesh_band=1,
            remesh_project=0,
            verbose=False,
        )
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "out.glb")
            # PNG textures — EXT_texture_webp falls back to grey on viewers
            # that don't implement the extension.
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
    steps = payload.get("steps")
    log.info(
        f"[{request_id}] submit: received; bucket={image_bucket} "
        f"key={image_key} steps={steps}"
    )

    if not image_bucket or not image_key:
        log.warning(f"[{request_id}] submit: missing image_bucket or image_key")
        return {"error": "image_bucket and image_key are required"}

    call = TrellisInference().generate.spawn(
        image_bucket=image_bucket,
        image_key=image_key,
        request_id=request_id,
        steps=steps,
    )
    log.info(f"[{request_id}] submit: spawned call_id={call.object_id}")
    return {"call_id": call.object_id, "request_id": request_id}


@app.function(image=trellis_thin_image, timeout=120)
@modal.fastapi_endpoint(method="POST", requires_proxy_auth=True)
def poll(payload: dict[str, Any]) -> dict[str, Any]:
    """Non-blocking status check; returns running / done / failed / expired."""

    return poll_function_call(payload.get("call_id"), log)
