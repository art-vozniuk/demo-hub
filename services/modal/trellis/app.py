"""Modal app: TRELLIS.2 single-image → textured GLB mesh on GPU.

Endpoint-less: invoked by name through the gateway. Per-phase metrics
via InferenceMetrics. Deploy / preload via
services/modal/trellis/{deploy,preload}.py.
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
    upload_to_s3,
)
from common.metrics import InferenceMetrics


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
        "prometheus-client==0.20.0",
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
    .add_local_python_source("common.lib", "common.metrics")
)


# Module-level imports are captured by Modal's memory snapshot — they
# stay loaded after restore.
with trellis_image.imports():
    import o_voxel
    from PIL import Image
    from trellis2.pipelines import Trellis2ImageTo3DPipeline


def _warmup_pipeline(pipe: Any) -> None:
    """Force every JIT'd CUDA kernel along the full inference path to
    compile before the snapshot is captured: diffusion (pipe.run) +
    cumesh remesh + nvdiffrast texture bake (to_glb). Otherwise the
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
        modal.Secret.from_name("pushgateway"),
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
        self._to_cuda_s = 0.0
        log.info("enter: load() begin on GPU container")
        t0 = time.perf_counter()

        try:
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
        # Built here (snap=False) so each container gets its own identity.
        self.m = InferenceMetrics("trellis", "L40S")
        self.m.cold_start("to_cuda", getattr(self, "_to_cuda_s", 0.0))
        self.m.push()
        log.info(f"[{self.m.container_id}] post-restore: ready")

    @modal.exit()
    async def cleanup(self) -> None:
        self.m.push_uptime()

    @modal.method()
    def generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.init_error is not None or self.pipe is None:
            raise RuntimeError(
                f"TrellisInference init failed: {self.init_error!r}"
            )

        image_bucket = payload["image_bucket"]
        image_key = payload["image_key"]
        steps = payload.get("steps")
        request_id = uuid.uuid4().hex[:8]

        steps = steps if steps in ALLOWED_SAMPLER_STEPS else DEFAULT_SAMPLER_STEPS
        log.info(f"[{request_id}] inference: start; key={image_key}; steps={steps}")
        t0 = time.perf_counter()
        self.m.batch(1)

        t_dl = time.perf_counter()
        with self.m.phase("download"):
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
        with self.m.phase("gpu"):
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
        with self.m.phase("upload"):
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

            # Drop pivot to feet so the editor gizmo lands at the base, not the
            # bbox centre. Runs on serialized bytes via trimesh round-trip.
            glb_bytes = _drop_pivot_to_feet(glb_bytes, request_id)
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

        self.m.push()
        return {
            "result_url": result_url,
            "glb_size_bytes": len(glb_bytes),
        }
