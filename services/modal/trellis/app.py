"""Modal app: TRELLIS.2 single-image → textured GLB mesh on GPU.

Endpoint-less: invoked by name through the gateway. Per-phase timings
ride back to dispatch in the response `_obs` block (common.instrument).
Deploy / preload via services/modal/trellis/{deploy,preload}.py.
"""

from __future__ import annotations

import io
import os
import tempfile
import time
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


GPU_NAME = "L40S"
SCALEDOWN_WINDOW_S = 10


MODEL_REPO = "microsoft/TRELLIS.2-4B"
MODEL_LOCAL_DIR = f"{MODEL_DIR}/trellis2-4b"
# HF cache lives on the volume so transitive downloads survive scaledowns.
HF_CACHE_DIR = f"{MODEL_DIR}/hf_cache"
# Pipeline configs reference two restricted repos; preload rewrites both:
#   dinov3 (Meta, gated; commercial OK with a "Built with DINOv3" attribution)
#     -> camenduru open mirror (same weights, ungated).
#   RMBG-2.0 (BRIA, CC BY-NC / non-commercial) -> BiRefNet (MIT, same arch,
#     loaded by the identical AutoModelForImageSegmentation interface).
HF_REPO_REWRITES = {
    "facebook/dinov3-vitl16-pretrain-lvd1689m": "camenduru/dinov3-vitl16-pretrain-lvd1689m",
    # Both spellings, so a volume already rewritten to the mirror is re-pointed.
    "briaai/RMBG-2.0": "ZhengPeng7/BiRefNet",
    "camenduru/RMBG-2.0": "ZhengPeng7/BiRefNet",
}
HF_AUX_REPOS = list(
    dict.fromkeys(["microsoft/TRELLIS-image-large", *HF_REPO_REWRITES.values()])
)

# Texture bake size. 4096 is upstream's default but UV-space rasterization
# scales O(N²) — at 4096 it stalls; 2048 keeps detail without the slowdown.
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
# Absolute path so the build doesn't depend on modal's working directory.
_POSTPROCESS_PATCH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "trellis_patches", "postprocess.py"
)

trellis_image = (
    modal.Image.from_registry(
        f"nvidia/cuda:{CUDA_TAG}-devel-ubuntu22.04", add_python="3.11"
    )
    .apt_install(
        "git",
        "build-essential",
        "ninja-build",
        "cmake",
        # GL/EGL stack for headless GL-backed libraries.
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
        "sentry-sdk>=2.42.0",
        # PyTorch3D (MIT) pure-Python deps — installed here to keep the
        # GPU run_commands layer focused on CUDA compilation.
        "fvcore",
        "iopath",
        extra_options="--extra-index-url https://download.pytorch.org/whl/cu124",
    )
    .env(
        {
            "HF_HUB_ENABLE_HF_TRANSFER": "1",
            "HF_HOME": HF_CACHE_DIR,
            "TRANSFORMERS_OFFLINE": "0",
            # Portable spconv backend.
            "SPCONV_ALGO": "native",
            # Headless EGL for OpenGL-backed libraries in the image.
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
    # Heavy installs that DON'T depend on the patched postprocess.py go
    # first, ahead of add_local_file, so editing the patch never rebuilds
    # the slow pytorch3d source build below.
    # FlexGEMM and CuMesh first: o-voxel pyproject lists them as git+
    # runtime deps, pre-installing lets o-voxel pass --no-deps.
    .run_commands(
        f"git clone --recursive https://github.com/microsoft/TRELLIS.2.git {TRELLIS_SRC}",
        "git clone --recursive https://github.com/JeffreyXiang/FlexGEMM.git /tmp/extensions/FlexGEMM",
        "pip install /tmp/extensions/FlexGEMM --no-build-isolation",
        "git clone --recursive https://github.com/JeffreyXiang/CuMesh.git /tmp/extensions/CuMesh",
        "pip install /tmp/extensions/CuMesh --no-build-isolation",
        # PyTorch3D (MIT) handles UV-space rasterization. Prebuilt wheel
        # first, source fallback (~20 min, cached after first build).
        "pip install --extra-index-url https://dl.fbaipublicfiles.com/pytorch3d/packaging/wheels/py311_cu124_pyt260/ pytorch3d"
        " || pip install 'git+https://github.com/facebookresearch/pytorch3d.git' --no-build-isolation",
        "pip install flash-attn==2.7.3 --no-build-isolation",
        "pip install git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8",
        gpu="A10G",
    )
    # Patched postprocess.py + o-voxel install LAST: editing the patch reruns
    # only these two cheap layers. copy=True bakes the file into a build
    # layer so the cp below can see it.
    .add_local_file(
        _POSTPROCESS_PATCH,
        "/tmp/postprocess_p3d.py",
        copy=True,
    )
    .run_commands(
        # Swap in our PyTorch3D postprocess, then install o-voxel (folder
        # o-voxel with a hyphen, Python package o_voxel).
        f"cp /tmp/postprocess_p3d.py {TRELLIS_SRC}/o-voxel/o_voxel/postprocess.py",
        f"pip install {TRELLIS_SRC}/o-voxel --no-build-isolation --no-deps",
        gpu="A10G",
    )
    .add_local_python_source(
        "common.lib", "common.instrument", "common.constants", "common.sentry"
    )
)


# o_voxel (→flex_gemm→triton) and trellis2 init a CUDA driver at import, so
# they can't load on the CPU preload container. Only CPU-safe PIL stays a
# module global; the GPU class imports the rest in load() (snap=True), which
# still captures them in the memory snapshot.
with trellis_image.imports():
    from PIL import Image


def _warmup_pipeline(pipe: Any) -> None:
    """Force every JIT'd CUDA kernel along the full inference path to
    compile before the snapshot is captured: diffusion (pipe.run) +
    cumesh remesh + PyTorch3D texture bake (to_glb). Otherwise the
    first real request hits cold-JIT and export inflates ~3-5x.
    """

    image_path = f"{TRELLIS_SRC}/assets/example_image/T.png"
    mesh = pipe.run(Image.open(image_path).convert("RGB"))[0]
    mesh.simplify(16777216)
    o_voxel.postprocess.to_glb(
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


def _drop_pivot_to_feet(glb_bytes: bytes, request_id: str) -> bytes:
    """Shift POSITION accessors in-place so combined min(Y) == 0.

    Operates directly on the GLB binary: rewrites the POSITION float32
    sub-ranges in the BIN chunk and updates each accessor's min/max in
    the JSON chunk. Avoids re-encoding textures (which is what made the
    earlier trimesh round-trip slow on multi-MB textured meshes).
    """

    import struct
    import json
    import numpy as np

    if len(glb_bytes) < 28 or glb_bytes[:4] != b"glTF":
        log.warning(f"[{request_id}] pivot: not a GLB; skip")
        return glb_bytes

    json_len, json_type = struct.unpack("<II", glb_bytes[12:20])
    if json_type != 0x4E4F534A:
        log.warning(f"[{request_id}] pivot: malformed JSON chunk; skip")
        return glb_bytes
    gltf = json.loads(glb_bytes[20 : 20 + json_len])

    bin_hdr = 20 + json_len
    bin_len, bin_type = struct.unpack("<II", glb_bytes[bin_hdr : bin_hdr + 8])
    if bin_type != 0x004E4942:
        log.warning(f"[{request_id}] pivot: malformed BIN chunk; skip")
        return glb_bytes
    bin_start = bin_hdr + 8
    bin_data = bytearray(glb_bytes[bin_start : bin_start + bin_len])

    accessors = gltf.get("accessors", [])
    buffer_views = gltf.get("bufferViews", [])
    pos_ids = {
        prim.get("attributes", {}).get("POSITION")
        for mesh in gltf.get("meshes", [])
        for prim in mesh.get("primitives", [])
    }
    pos_ids.discard(None)
    if not pos_ids:
        log.warning(f"[{request_id}] pivot: no POSITION accessors")
        return glb_bytes

    def view_of(acc_idx: int):
        acc = accessors[acc_idx]
        bv = buffer_views[acc["bufferView"]]
        off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
        return np.frombuffer(
            bin_data, dtype=np.float32, count=acc["count"] * 3, offset=off
        ).reshape(-1, 3)

    min_y = min(float(view_of(i)[:, 1].min()) for i in pos_ids)
    dy = -min_y
    if abs(dy) < 1e-6:
        log.info(f"[{request_id}] pivot: already at Y=0")
        return glb_bytes

    for i in pos_ids:
        view_of(i)[:, 1] += dy
        acc = accessors[i]
        if "min" in acc and len(acc["min"]) >= 2:
            acc["min"][1] += dy
        if "max" in acc and len(acc["max"]) >= 2:
            acc["max"][1] += dy

    new_json = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    new_json += b" " * ((4 - len(new_json) % 4) % 4)
    new_bin = bytes(bin_data) + b"\x00" * ((4 - len(bin_data) % 4) % 4)
    total = 12 + 8 + len(new_json) + 8 + len(new_bin)

    out = bytearray()
    out += b"glTF"
    out += struct.pack("<II", 2, total)
    out += struct.pack("<II", len(new_json), 0x4E4F534A)
    out += new_json
    out += struct.pack("<II", len(new_bin), 0x004E4942)
    out += new_bin

    log.info(f"[{request_id}] pivot: shifted Y by {dy:+.4f} so min(Y)=0")
    return bytes(out)


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
    gpu=GPU_NAME,
    volumes={MODEL_DIR: volume},
    scaledown_window=SCALEDOWN_WINDOW_S,
    timeout=MODAL_FUNCTION_TIMEOUT_SECONDS,
    retries=modal.Retries(max_retries=0),
    # GPU snapshot keeps the GPU attached during snap=True, which is
    # required because flex_gemm/triton init driver state on import.
    enable_memory_snapshot=True,
    experimental_options={"enable_gpu_snapshot": True},
    secrets=[
        modal.Secret.from_name("supabase-s3"),
        modal.Secret.from_name("sentry"),
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

        global o_voxel

        self.pipe = None
        self.init_error: BaseException | None = None
        self._to_cuda_s = 0.0
        log.info("enter: load() begin on GPU container")
        t0 = time.perf_counter()

        try:
            import o_voxel
            from trellis2.pipelines import Trellis2ImageTo3DPipeline

            self.pipe = Trellis2ImageTo3DPipeline.from_pretrained(MODEL_LOCAL_DIR)
            from_pretrained_ms = (time.perf_counter() - t0) * 1000
            log.info(
                f"enter: from_pretrained({MODEL_LOCAL_DIR}) "
                f"finished in {from_pretrained_ms:.0f}ms"
            )

            t_gpu = time.perf_counter()
            self.pipe.cuda()
            self._to_cuda_s = time.perf_counter() - t_gpu
            log.info(f"enter: pipe.cuda() finished in {self._to_cuda_s * 1000:.0f}ms")
        except Exception as e:
            log.exception("enter: pipeline init failed")
            self.init_error = e
            return

        try:
            t_warm = time.perf_counter()
            _warmup_pipeline(self.pipe)
            warm_ms = (time.perf_counter() - t_warm) * 1000
            log.info(f"enter: full-pipeline warmup done in {warm_ms:.0f}ms")
        except Exception as e:
            log.warning(f"enter: warmup failed (non-fatal): {e!r}")

    @modal.enter(snap=False)
    def post_restore(self) -> None:
        init_sentry("trellis")
        # Built here (snap=False) so each container gets its own identity.
        self.runner = InferenceRunner(
            config="trellis",
            gpu=GPU_NAME,
            scaledown_window_s=SCALEDOWN_WINDOW_S,
            log=log,
            cold={"to_cuda": getattr(self, "_to_cuda_s", 0.0)},
        )
        log.info(f"[{self.runner.container_id}] post-restore: ready")

    @modal.method()
    def generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.init_error is not None or self.pipe is None:
            raise RuntimeError(
                f"TrellisInference init failed: {self.init_error!r}"
            )

        image_bucket = payload["image_bucket"]
        image_key = payload["image_key"]
        steps = payload.get("steps")

        steps = steps if steps in ALLOWED_SAMPLER_STEPS else DEFAULT_SAMPLER_STEPS

        with self.runner.start(payload) as run:
            log.info(
                f"[{run.request_id}] inference: start; key={image_key}; steps={steps}"
            )
            run.batch(1)

            with run.phase("download"):
                raw = download_from_s3(image_bucket, image_key)
                raw = bake_exif_orientation(raw)

            image = Image.open(io.BytesIO(raw)).convert("RGB")
            log.info(
                f"[{run.request_id}] inference: decoded input "
                f"{image.width}x{image.height}, {len(raw)} bytes"
            )

            # All three samplers default from pipeline.json (steps=12); kwargs
            # here override per-request.
            steps_override = {"steps": steps}
            with run.phase("gpu"):
                mesh = self.pipe.run(
                    image,
                    sparse_structure_sampler_params=steps_override,
                    shape_slat_sampler_params=steps_override,
                    tex_slat_sampler_params=steps_override,
                )[0]
                # Cap raw face count before export.
                mesh.simplify(16777216)

            with run.phase("export"):
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
                    # PNG textures — EXT_texture_webp falls back to grey on
                    # viewers that don't implement the extension.
                    glb.export(out_path)
                    with open(out_path, "rb") as f:
                        glb_bytes = f.read()

                # Drop pivot to feet so the editor gizmo lands at the base,
                # not the bbox centre. Runs on serialized bytes via trimesh
                # round-trip.
                glb_bytes = _drop_pivot_to_feet(glb_bytes, run.request_id)
            log.info(
                f"[{run.request_id}] export: glb_size="
                f"{len(glb_bytes) / (1024 * 1024):.1f} MB"
            )

            with run.phase("upload"):
                result_url = upload_to_s3(
                    data_bytes=glb_bytes,
                    bucket=image_bucket,
                    folder="trellis_results",
                    extension="glb",
                )

            return run.finish(
                {
                    "result_url": result_url,
                    "glb_size_bytes": len(glb_bytes),
                }
            )
