"""Modal app: FLUX.2 klein image-conditioned editing on A10G.

Deploy:
    modal deploy services/modal/app.py

Preload weights into the volume (one-shot):
    modal run services/modal/app.py::preload_weights
"""

from __future__ import annotations

import base64
import io
import logging
import os
import time
import uuid
from typing import Any

import modal


APP_NAME = "demo-hub-flux"
VOLUME_NAME = "flux-models"
MODEL_DIR = "/models"
MODEL_REPO = "black-forest-labs/FLUX.2-klein-4B"
MODEL_LOCAL_DIR = f"{MODEL_DIR}/flux2-klein-4b"


# Stdout is captured by Modal and shown in the dashboard "Logs" tab,
# so plain logging is enough — no extra sink needed.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("flux")


app = modal.App(APP_NAME)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)


# Image: built once, cached forever, reused across deploys.
flux_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "ffmpeg", "libgl1", "libglib2.0-0")
    .pip_install(
        # Torch/torchvision pinned together — CUDA ABI mismatch hurts.
        "torch==2.5.1",
        "torchvision==0.20.1",
        # Flux2KleinPipeline only landed on diffusers main; no PyPI release
        # ships it yet. The rest of the ML stack (transformers, accelerate,
        # safetensors, tokenizers) is left unpinned so pip can resolve a
        # mutually-compatible set against this dev build. Pin again once a
        # versioned release cuts.
        "git+https://github.com/huggingface/diffusers.git",
        "transformers",
        "accelerate",
        "huggingface-hub[hf-transfer]>=0.34.0",
        "Pillow==11.0.0",
        "fastapi[standard]==0.115.6",
        "pydantic==2.10.3",
    )
    .env(
        {
            "HF_HUB_ENABLE_HF_TRANSFER": "1",
            "HF_HOME": "/root/.cache/huggingface",
            "TRANSFORMERS_OFFLINE": "0",
        }
    )
)


with flux_image.imports():
    import torch
    from diffusers import Flux2KleinPipeline
    from PIL import Image


@app.function(
    image=flux_image,
    volumes={MODEL_DIR: volume},
    timeout=60 * 60,
    secrets=[modal.Secret.from_name("huggingface", required_keys=[])],
)
def preload_weights() -> str:
    """Download FLUX.2 klein 4B into the persistent volume.

    Run once: `modal run services/modal/app.py::preload_weights`.
    Re-running is a no-op when files are already up to date.
    """

    from huggingface_hub import snapshot_download

    t0 = time.perf_counter()
    os.makedirs(MODEL_LOCAL_DIR, exist_ok=True)
    snapshot_download(
        repo_id=MODEL_REPO,
        local_dir=MODEL_LOCAL_DIR,
        token=os.environ.get("HF_TOKEN"),
        max_workers=8,
    )
    volume.commit()
    log.info(f"preload done: {MODEL_LOCAL_DIR} in {(time.perf_counter()-t0):.1f}s")
    return MODEL_LOCAL_DIR


@app.cls(
    image=flux_image,
    gpu="A10G",
    volumes={MODEL_DIR: volume},
    scaledown_window=10,
    timeout=600,
    enable_memory_snapshot=True,
)
@modal.concurrent(max_inputs=1)
class FluxInference:
    @modal.enter(snap=True)
    def load_to_cpu(self) -> None:
        """Snapshot hook: runs ONCE on a CPU-only container before Modal
        captures the memory snapshot. Loads pipeline weights from the
        volume into RAM. The snapshot freezes RAM at this point, so all
        future cold starts skip this expensive disk read."""

        t0 = time.perf_counter()
        self.pipe = Flux2KleinPipeline.from_pretrained(
            MODEL_LOCAL_DIR,
            torch_dtype=torch.bfloat16,
        )
        log.info(f"snap-load: from_pretrained in {(time.perf_counter()-t0)*1000:.0f}ms")

    @modal.enter(snap=False)
    def move_to_gpu(self) -> None:
        """Post-restore hook: runs on every cold start AFTER snapshot
        restore (or fresh start), this time on the real GPU container.
        Cheap because weights are already in RAM — we just shuttle them
        across PCIe to the A10G."""

        t0 = time.perf_counter()
        self.pipe.to("cuda")
        log.info(f"post-restore: to(cuda) in {(time.perf_counter()-t0)*1000:.0f}ms")

    @modal.method()
    def generate(
        self,
        image_b64: str,
        prompt: str,
        request_id: str,
        guidance_scale: float = 1.0,
        num_inference_steps: int = 4,
        max_side: int = 1024,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()

        raw = base64.b64decode(image_b64)
        init = Image.open(io.BytesIO(raw)).convert("RGB")

        # Cap the longest side. Klein 4B itself fits comfortably on A10G,
        # but very large inputs blow up the encoder activations.
        w, h = init.size
        scale = max_side / max(w, h)
        if scale < 1.0:
            init = init.resize(
                (int(round(w * scale)), int(round(h * scale))), Image.LANCZOS
            )

        t_inf = time.perf_counter()
        out = self.pipe(
            image=init,
            prompt=prompt,
            guidance_scale=guidance_scale,
            num_inference_steps=num_inference_steps,
        )
        inference_ms = (time.perf_counter() - t_inf) * 1000

        result_image: "Image.Image" = out.images[0]
        buf = io.BytesIO()
        result_image.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        total_ms = (time.perf_counter() - t0) * 1000
        log.info(
            f"[{request_id}] {init.width}x{init.height} → "
            f"{result_image.width}x{result_image.height} "
            f"({len(png_bytes)/1e6:.1f}MB PNG) in {total_ms:.0f}ms "
            f"(inference {inference_ms:.0f}ms)"
        )
        return {
            "image_b64": base64.b64encode(png_bytes).decode("ascii"),
            "width": result_image.width,
            "height": result_image.height,
        }


@app.function(
    image=flux_image,
    timeout=600,
)
@modal.fastapi_endpoint(method="POST", requires_proxy_auth=True)
def generate(payload: dict[str, Any]) -> dict[str, Any]:
    """Public HTTP entry point. Gated by Modal proxy-auth — Modal
    validates incoming Modal-Key/Modal-Secret headers against tokens
    issued in the dashboard at /settings/proxy-auth-tokens."""

    request_id = uuid.uuid4().hex[:8]
    t0 = time.perf_counter()

    image_b64 = payload.get("image_b64")
    prompt = payload.get("prompt")

    if not image_b64 or not prompt:
        log.warning(f"[{request_id}] missing image_b64 or prompt")
        return {"error": "image_b64 and prompt are required"}

    guidance_scale = float(payload.get("guidance_scale", 1.0))
    num_inference_steps = int(payload.get("num_inference_steps", 4))

    inference = FluxInference()
    result = inference.generate.remote(
        request_id=request_id,
        image_b64=image_b64,
        prompt=prompt,
        guidance_scale=guidance_scale,
        num_inference_steps=num_inference_steps,
    )

    log.info(f"[{request_id}] endpoint done in {(time.perf_counter()-t0)*1000:.0f}ms")
    return result
