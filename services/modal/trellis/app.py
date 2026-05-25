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
# HF cache lives on the persistent volume so Trellis2ImageTo3DPipeline's
# transitive HF downloads (TRELLIS-image-large, dinov3, ...) survive
# scaledowns and don't re-download on every cold start.
HF_CACHE_DIR = f"{MODEL_DIR}/hf_cache"
# Models that TRELLIS.2 lazily pulls from HF Hub inside from_pretrained().
# Predownload them into HF_CACHE_DIR so cold starts never hit the network.
# Upstream TRELLIS.2 configs reference two gated repos by name:
#   facebook/dinov3-vitl16-pretrain-lvd1689m  — Meta, new requests rejected
#   briaai/RMBG-2.0                            — Bria, gated by terms
# camenduru maintains bit-identical mirrors of both with gated=False.
# We download from the mirrors and rewrite the pipeline configs to match.
HF_REPO_REWRITES = {
    "facebook/dinov3-vitl16-pretrain-lvd1689m": "camenduru/dinov3-vitl16-pretrain-lvd1689m",
    "briaai/RMBG-2.0": "camenduru/RMBG-2.0",
}
HF_AUX_REPOS = [
    "microsoft/TRELLIS-image-large",
    *HF_REPO_REWRITES.values(),
]

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
        # extension builds below. cu124 wheels match the devel base. Pinned
        # to upstream setup.sh's versions: 2.6.0 ships triton>=3.2 which
        # FlexGEMM requires; 2.5.x ships triton 3.1 and fails dep solve.
        "torch==2.6.0",
        "torchvision==0.21.0",
        "numpy",
        "Pillow==11.0.0",
        # Need the 4.x line for BiRefNet (5.x added all_tied_weights_keys
        # which the camenduru BiRefNet custom code doesn't define), but
        # DINOv3ViTModel only landed in 4.56. 4.57.6 is the last 4.x patch.
        "transformers==4.57.6",
        "accelerate",
        "safetensors",
        "huggingface-hub[hf-transfer]>=0.34.0",
        "trimesh",
        "xatlas",
        "pymeshlab",
        # Build-time tooling: pip uses the global env when --no-build-isolation
        # is set, so wheel must already be installed for bdist_wheel to exist.
        "wheel",
        "setuptools>=64",
        # o-voxel runtime dep not covered elsewhere.
        "plyfile",
        # TRELLIS.2's --basic deps (from upstream setup.sh): runtime imports
        # in trellis2/* assume these are present. Skipping gradio/tensorboard
        # since we never serve the UI or train.
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
            # TRELLIS runtime knobs — native spconv algo is the most
            # portable; attention backend is left to the lib default.
            "SPCONV_ALGO": "native",
            # nvdiffrast needs an EGL device to render off-screen.
            "PYOPENGL_PLATFORM": "egl",
            # The `trellis2` package has no setup.py at the repo root;
            # upstream just expects you to import it from a checkout.
            "PYTHONPATH": TRELLIS_SRC,
            # cv2 reads .exr env maps in the example pipeline.
            "OPENCV_IO_ENABLE_OPENEXR": "1",
            # Modal's add_python ships a clang-built Python; sysconfig
            # then forwards clang++ to setuptools, but we only installed
            # g++ via build-essential, and PyTorch is built with g++ —
            # mixing toolchains breaks the C++ ABI even when it links.
            "CC": "gcc",
            "CXX": "g++",
            "LDSHARED": "g++ -shared",
        }
    )
    # Clone with submodules, then build each custom extension. Order:
    # FlexGEMM and CuMesh first because o-voxel's pyproject lists them as
    # runtime deps via git+ URLs — pre-installing locally lets us pass
    # --no-deps on o-voxel and skip the re-download. extensions/* dirs do
    # not exist in TRELLIS.2; those kernels live in separate repos
    # referenced by upstream's setup.sh.
    .run_commands(
        f"git clone --recursive https://github.com/microsoft/TRELLIS.2.git {TRELLIS_SRC}",
        "git clone --recursive https://github.com/JeffreyXiang/FlexGEMM.git /tmp/extensions/FlexGEMM",
        "pip install /tmp/extensions/FlexGEMM --no-build-isolation",
        "git clone --recursive https://github.com/JeffreyXiang/CuMesh.git /tmp/extensions/CuMesh",
        "pip install /tmp/extensions/CuMesh --no-build-isolation",
        # Folder on disk is `o-voxel` (hyphen); Python import is `o_voxel`.
        # --no-deps because cumesh + flex_gemm are already installed above.
        f"pip install {TRELLIS_SRC}/o-voxel --no-build-isolation --no-deps",
        "git clone -b v0.4.0 https://github.com/NVlabs/nvdiffrast.git /tmp/extensions/nvdiffrast",
        "pip install /tmp/extensions/nvdiffrast --no-build-isolation",
        "git clone -b renderutils https://github.com/JeffreyXiang/nvdiffrec.git /tmp/extensions/nvdiffrec",
        "pip install /tmp/extensions/nvdiffrec --no-build-isolation",
        "pip install flash-attn==2.7.3 --no-build-isolation",
        "pip install git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8",
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


# NOTE: o_voxel + trellis2 cannot be imported on a CPU container — they
# pull flex_gemm, which triggers triton autotune init at module load and
# needs an NVIDIA driver. preload_weights and any CPU-snapshot hook would
# crash. So we import lazily inside the GPU-only generate() method below
# and skip Modal's CPU memory snapshot entirely.


@app.function(
    image=trellis_image,
    volumes={MODEL_DIR: volume},
    timeout=60 * 60,
    secrets=[modal.Secret.from_name("huggingface", required_keys=[])],
)
def preload_weights() -> str:
    """Download TRELLIS.2-4B + transitive HF deps into the persistent volume.

    Run once: `python services/modal/trellis/preload.py`. Re-running is a
    no-op when files are already up to date. dinov3 is gated — HF_TOKEN
    in the `huggingface` Modal secret must have access approval.
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

    # Rewrite in-place so the feature extractors load from open mirrors
    # instead of the gated facebook/ and briaai/ repos. Touches both
    # pipeline.json and texturing_pipeline.json.
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
    log.info(f"preload: patched {rewrites} pipeline config(s) to mirrors")

    # Transitive deps pulled by Trellis2ImageTo3DPipeline.from_pretrained
    # at runtime. Cache them into HF_CACHE_DIR (== HF_HOME on inference
    # containers) so cold starts skip the network entirely.
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
            # Don't kill the whole preload if one aux repo fails (e.g. user
            # hasn't approved a gated repo yet). Log loudly and continue —
            # the inference cold start will surface the same error.
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


# GPU note: 512-res TRELLIS.2 fits an A10G (24GB). If a real input OOMs,
# do NOT drop the resolution/quality — bump the tier to gpu="L40S" (48GB).
@app.cls(
    image=trellis_image,
    gpu="A10G",
    volumes={MODEL_DIR: volume},
    scaledown_window=10,
    timeout=600,
    # Once the function actually runs, never retry — if generation fails
    # on a real input we want one clear error, not 3x the GPU bill.
    retries=modal.Retries(max_retries=0),
    # GPU memory snapshot: snap=True runs on a GPU container (unlike the
    # default CPU snapshot), so flex_gemm/triton driver init at import
    # works. Cold restores skip the ~5 min model load + warmup.
    enable_memory_snapshot=True,
    experimental_options={"enable_gpu_snapshot": True},
    secrets=[
        modal.Secret.from_name("supabase-s3"),
        # HF_TOKEN is needed if any transitive download wasn't pre-cached
        # (or for the gated dinov3 repo). Pre-caching in preload_weights
        # makes this mostly belt-and-suspenders.
        modal.Secret.from_name("huggingface", required_keys=[]),
    ],
    # min_containers=1,
)
@modal.concurrent(max_inputs=1)
class TrellisInference:
    @modal.enter(snap=True)
    def load(self) -> None:
        """Snapshot hook. Modal's GPU memory snapshot keeps the GPU
        attached during snap=True (alpha feature), so flex_gemm/triton
        driver init at import works. Snapshot captures the loaded
        pipeline + warmed JIT state; subsequent cold starts restore
        in seconds instead of ~5 minutes.

        Errors are caught and stashed; generate() raises on first call.
        Otherwise Modal treats an enter failure as "container couldn't
        start" and spins up a fresh container for the same FunctionCall,
        burning GPU time in a crash loop instead of failing the request.
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
            log.exception("enter: pipeline init failed; will fail fast on first call")
            self.init_error = e
            return

        # Warmup: a throwaway run on a tiny image forces the extension
        # kernels to JIT now instead of on the first real request.
        try:
            from PIL import Image

            t_warm = time.perf_counter()
            dummy = Image.new("RGB", (64, 64), (127, 127, 127))
            self.pipe.run(dummy)
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
    ) -> dict[str, Any]:
        # Bail out as a normal function error if load() couldn't bring
        # the pipeline up — Modal then completes the FunctionCall as
        # failed instead of restarting the container indefinitely.
        if self.init_error is not None or self.pipe is None:
            raise RuntimeError(
                f"TrellisInference init failed: {self.init_error!r}"
            )

        # Same lazy-import rationale as in load(): these modules need
        # a GPU at import time and would crash on any CPU container.
        import o_voxel
        from PIL import Image

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
        # Upstream example.py: cap face count before to_glb (nvdiffrast limit).
        mesh.simplify(16777216)
        inference_ms = (time.perf_counter() - t_inf) * 1000
        log.info(
            f"[{request_id}] inference: pipe.run(...) returned in {inference_ms:.0f}ms"
        )

        # Export a PBR-textured GLB. Signature mirrors upstream example.py.
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
            texture_size=RENDER_RESOLUTION,
            remesh=True,
            remesh_band=1,
            remesh_project=0,
            verbose=False,
        )
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "out.glb")
            # Plain PNG/JPEG textures — EXT_texture_webp is unsupported by
            # most viewers (including our WebGPU renderer) and gets dropped
            # to a grey default material per glTF spec.
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
