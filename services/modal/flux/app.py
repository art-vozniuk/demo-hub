"""Modal app: FLUX.2 klein image-conditioned editing on A10G.

Deploy / preload via services/modal/flux/{deploy,preload}.py.
"""

from __future__ import annotations

import inspect
import io
import os
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


MODEL_REPO = "black-forest-labs/FLUX.2-klein-4B"
MODEL_LOCAL_DIR = f"{MODEL_DIR}/flux2-klein-4b"

GPU_NAME = "A10G"
SCALEDOWN_WINDOW_S = 2


log = configure_logging("flux")
app, volume = make_app("demo-hub-flux", "flux-models")


flux_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "ffmpeg", "libgl1", "libglib2.0-0")
    .pip_install(
        # FLUX.2-klein needs torch>=2.7 (float8_e8m0fnu, absent in 2.5.1)
        # + diffusers-main; commit + transformers pinned for reproducibility.
        "torch==2.7.1",
        "torchvision==0.22.1",
        "git+https://github.com/huggingface/diffusers.git@2c7efb95349296cf6bcce981ea036275a82a94df",
        "transformers==5.10.2",
        "accelerate",
        "huggingface-hub[hf-transfer]>=0.34.0",
        "Pillow==11.0.0",
        "fastapi[standard]==0.115.6",
        "pydantic==2.10.3",
        "boto3==1.35.92",
        "sentry-sdk>=2.42.0",
    )
    .env(
        {
            "HF_HUB_ENABLE_HF_TRANSFER": "1",
            "HF_HOME": "/root/.cache/huggingface",
            "TRANSFORMERS_OFFLINE": "0",
        }
    )
    # Modal no longer auto-mounts sibling files; ship common.* explicitly.
    .add_local_python_source(
        "common.lib", "common.instrument", "common.constants", "common.sentry"
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

    Run once: `python services/modal/flux/preload.py`. Re-running is a
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
        f"(total {total_ms:.0f}ms); volume now contains weights at {MODEL_LOCAL_DIR}"
    )

    return MODEL_LOCAL_DIR


@app.cls(
    image=flux_image,
    gpu=GPU_NAME,
    volumes={MODEL_DIR: volume},
    scaledown_window=SCALEDOWN_WINDOW_S,
    timeout=MODAL_FUNCTION_TIMEOUT_SECONDS,
    enable_memory_snapshot=True,
    secrets=[
        modal.Secret.from_name("supabase-s3"),
        modal.Secret.from_name("sentry"),
    ],
    # min_containers=1,
)
@modal.concurrent(max_inputs=1)
class FluxInference:
    @modal.enter(snap=True)
    def load_to_cpu(self) -> None:
        """Snapshot hook: runs ONCE on a CPU-only container before Modal
        captures the memory snapshot. Loads pipeline weights from the
        volume into RAM. The snapshot freezes RAM at this point, so all
        future cold starts skip this expensive disk read."""

        log.info(
            "snapshot-load: load_to_cpu() begin; runs once during snapshot "
            "creation on a CPU container (no GPU attached here yet)"
        )
        t0 = time.perf_counter()

        self.pipe = Flux2KleinPipeline.from_pretrained(
            MODEL_LOCAL_DIR,
            torch_dtype=torch.bfloat16,
        )
        # Snapshotted along with the weights — every restored container
        # reports how expensive its snapshot was to build.
        self._snapshot_load_s = time.perf_counter() - t0
        log.info(
            f"snapshot-load: from_pretrained({MODEL_LOCAL_DIR}) "
            f"finished in {self._snapshot_load_s * 1000:.0f}ms; "
            "Modal will snapshot RAM after this returns"
        )

    @modal.enter(snap=False)
    def move_to_gpu(self) -> None:
        """Post-restore hook: runs on every cold start AFTER snapshot
        restore (or fresh start), this time on the real GPU container.
        Cheap because weights are already in RAM — we just shuttle them
        across PCIe to the A10G."""

        init_sentry("flux")
        log.info(
            "post-restore: move_to_gpu() begin; runs after each container "
            "start, with the GPU now attached"
        )
        wall0 = time.time()
        t0 = time.perf_counter()
        self.pipe.to("cuda")
        to_cuda_s = time.perf_counter() - t0
        # Per-step timing needs diffusers' step callback; probe once.
        self._supports_step_cb = (
            "callback_on_step_end" in inspect.signature(self.pipe.__call__).parameters
        )
        self.runner = InferenceRunner(
            config="flux",
            gpu=GPU_NAME,
            scaledown_window_s=SCALEDOWN_WINDOW_S,
            log=log,
            cold={
                "snapshot_load": getattr(self, "_snapshot_load_s", 0.0),
                "to_cuda": to_cuda_s,
            },
            cold_wall=(wall0, wall0 + to_cuda_s),
        )
        log.info(
            f"post-restore: pipe.to(cuda) finished in {to_cuda_s * 1000:.0f}ms; "
            "ready to serve"
        )

    @modal.method()
    def generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        image_bucket = payload["image_bucket"]
        image_key = payload["image_key"]
        prompt = payload["prompt"]
        guidance_scale = float(payload.get("guidance_scale", 1.0))
        num_inference_steps = int(payload.get("num_inference_steps", 4))
        max_side = int(payload.get("max_side", 1024))

        with self.runner.start(payload) as run:
            log.info(
                f"[{run.request_id}] inference: start; prompt_len={len(prompt)} "
                f"steps={num_inference_steps} guidance={guidance_scale} "
                f"max_side={max_side}"
            )

            with run.phase("download"):
                raw = download_from_s3(image_bucket, image_key)

            with run.phase("preprocess"):
                raw = bake_exif_orientation(raw)
                init = Image.open(io.BytesIO(raw)).convert("RGB")
                log.info(
                    f"[{run.request_id}] inference: decoded input "
                    f"{init.width}x{init.height}, {len(raw)} bytes"
                )
                # Cap the longest side. Klein 4B itself fits comfortably on
                # A10G, but very large inputs blow up encoder activations.
                w, h = init.size
                scale = max_side / max(w, h)
                if scale < 1.0:
                    new_w = int(round(w * scale))
                    new_h = int(round(h * scale))
                    log.info(
                        f"[{run.request_id}] inference: resizing "
                        f"{w}x{h} -> {new_w}x{new_h} (max_side={max_side})"
                    )
                    init = init.resize((new_w, new_h), Image.LANCZOS)

            step_ends: list[float] = []
            extra: dict[str, Any] = {}
            if self._supports_step_cb:

                def _on_step_end(pipe, step, timestep, callback_kwargs):
                    step_ends.append(time.time())
                    return callback_kwargs

                extra["callback_on_step_end"] = _on_step_end

            with run.phase("gpu"):
                gpu_t0 = time.time()
                out = self.pipe(
                    image=init,
                    prompt=prompt,
                    guidance_scale=guidance_scale,
                    num_inference_steps=num_inference_steps,
                    **extra,
                )
                gpu_t1 = time.time()

            # Sentry-only breakdown of the opaque pipe() call: text-encode
            # is inseparable from step 1 (the callback fires at step ends).
            if step_ends:
                run.retro_span("gpu.encode_step1", gpu_t0, step_ends[0])
                if len(step_ends) > 1:
                    run.retro_span("gpu.denoise_steps", step_ends[0], step_ends[-1])
                    per_step_ms = (
                        (step_ends[-1] - step_ends[0]) / (len(step_ends) - 1) * 1000
                    )
                    run.tag("gpu.ms_per_step", int(round(per_step_ms)))
                run.retro_span("gpu.vae_decode", step_ends[-1], gpu_t1)
            run.tag("steps", num_inference_steps)
            run.tag("guidance", guidance_scale)
            run.tag("resolution", f"{init.width}x{init.height}")

            with run.phase("postprocess"):
                result_image: "Image.Image" = out.images[0]
                buf = io.BytesIO()
                result_image.save(buf, format="PNG")
                png_bytes = buf.getvalue()

            with run.phase("upload"):
                result_url = upload_to_s3(
                    data_bytes=png_bytes,
                    bucket=image_bucket,
                    folder="generative_results",
                    extension="png",
                )

            run.batch(1)
            return run.finish(
                {
                    "result_url": result_url,
                    "width": result_image.width,
                    "height": result_image.height,
                }
            )
