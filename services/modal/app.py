"""Modal app: FLUX.2 klein image-conditioned editing on A10G.

Deploy:
    modal deploy services/modal/app.py

Preload weights into the volume (one-shot):
    modal run services/modal/app.py::preload_weights
"""

from __future__ import annotations

import base64
import io
from typing import Any

import modal


APP_NAME = "demo-hub-flux"
VOLUME_NAME = "flux-models"
MODEL_DIR = "/models"
MODEL_REPO = "black-forest-labs/FLUX.2-klein-4B"
MODEL_LOCAL_DIR = f"{MODEL_DIR}/flux2-klein-4b"


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

    import os
    from huggingface_hub import snapshot_download

    os.makedirs(MODEL_LOCAL_DIR, exist_ok=True)
    snapshot_download(
        repo_id=MODEL_REPO,
        local_dir=MODEL_LOCAL_DIR,
        token=os.environ.get("HF_TOKEN"),
        max_workers=8,
    )
    volume.commit()
    return MODEL_LOCAL_DIR


@app.cls(
    image=flux_image,
    gpu="A10G",
    volumes={MODEL_DIR: volume},
    scaledown_window=120,
    timeout=600,
    enable_memory_snapshot=True,
    secrets=[modal.Secret.from_name("modal-proxy-auth", required_keys=[])],
)
@modal.concurrent(max_inputs=1)
class FluxInference:
    @modal.enter(snap=True)
    def load(self) -> None:
        """Loads pipeline weights from the volume onto the GPU. Snapshot
        captures RAM after this returns, so subsequent cold starts skip
        the heavy disk + GPU upload."""

        self.pipe = Flux2KleinPipeline.from_pretrained(
            MODEL_LOCAL_DIR,
            torch_dtype=torch.bfloat16,
        )
        self.pipe.to("cuda")

    @modal.method()
    def generate(
        self,
        image_b64: str,
        prompt: str,
        guidance_scale: float = 1.0,
        num_inference_steps: int = 4,
        max_side: int = 1024,
    ) -> dict[str, Any]:
        raw = base64.b64decode(image_b64)
        init = Image.open(io.BytesIO(raw)).convert("RGB")

        # Cap the longest side. Klein 4B itself fits comfortably on A10G,
        # but very large inputs blow up the encoder activations.
        w, h = init.size
        scale = max_side / max(w, h)
        if scale < 1.0:
            init = init.resize(
                (int(round(w * scale)), int(round(h * scale))),
                Image.LANCZOS,
            )

        out = self.pipe(
            image=init,
            prompt=prompt,
            guidance_scale=guidance_scale,
            num_inference_steps=num_inference_steps,
        )
        result_image: "Image.Image" = out.images[0]

        buf = io.BytesIO()
        result_image.save(buf, format="PNG")
        return {
            "image_b64": base64.b64encode(buf.getvalue()).decode("ascii"),
            "width": result_image.width,
            "height": result_image.height,
        }


@app.function(
    image=flux_image,
    secrets=[modal.Secret.from_name("modal-proxy-auth", required_keys=[])],
    timeout=600,
)
@modal.fastapi_endpoint(method="POST", requires_proxy_auth=True)
def generate(payload: dict[str, Any]) -> dict[str, Any]:
    """Public HTTP entry point. Gated by Modal proxy-auth so only the
    dispatch worker (which holds the secret pair) can invoke it."""

    image_b64 = payload.get("image_b64")
    prompt = payload.get("prompt")
    if not image_b64 or not prompt:
        return {"error": "image_b64 and prompt are required"}

    inference = FluxInference()
    return inference.generate.remote(
        image_b64=image_b64,
        prompt=prompt,
        guidance_scale=float(payload.get("guidance_scale", 1.0)),
        num_inference_steps=int(payload.get("num_inference_steps", 4)),
    )
