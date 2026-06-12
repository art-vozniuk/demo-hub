"""FLUX.1 [schnell] text-to-image on L40S.

Endpoint-less: invoked by name through the gateway. Per-phase timings
ride back to dispatch in the response `_obs` block (common.instrument).
"""

from __future__ import annotations

import io
import os
import time
import uuid
from typing import Any

import modal

from common.constants import MODAL_FUNCTION_TIMEOUT_SECONDS
from common.instrument import InferenceRunner
from common.lib import (
    MODEL_DIR,
    configure_logging,
    make_app,
)
from common.sentry import init_sentry


MODEL_REPO = "black-forest-labs/FLUX.1-schnell"
MODEL_LOCAL_DIR = f"{MODEL_DIR}/flux1-schnell"

# schnell bfloat16 weights are ~24GB — A10G's 22GB OOMs on .to("cuda").
GPU_NAME = "L40S"
SCALEDOWN_WINDOW_S = 2


log = configure_logging("flux_t2i")
app, volume = make_app("demo-hub-flux-t2i", "flux-t2i-models")


flux_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "ffmpeg", "libgl1", "libglib2.0-0")
    .pip_install(
        "torch==2.5.1",
        "torchvision==0.20.1",
        "diffusers==0.32.2",
        "transformers==4.46.3",
        "accelerate==1.2.1",
        "sentencepiece==0.2.0",
        "protobuf==5.29.2",
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
    .add_local_python_source(
        "common.lib", "common.instrument", "common.constants", "common.sentry"
    )
)


with flux_image.imports():
    import torch
    from diffusers import FluxPipeline


@app.function(
    image=flux_image,
    volumes={MODEL_DIR: volume},
    timeout=60 * 60,
    secrets=[modal.Secret.from_name("huggingface", required_keys=[])],
)
def preload_weights() -> str:
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
)
@modal.concurrent(max_inputs=1)
class FluxT2IInference:
    @modal.enter(snap=True)
    def load_to_cpu(self) -> None:
        log.info("snapshot-load: load_to_cpu() begin")
        t0 = time.perf_counter()
        self.pipe = FluxPipeline.from_pretrained(
            MODEL_LOCAL_DIR,
            torch_dtype=torch.bfloat16,
        )
        self._snapshot_load_s = time.perf_counter() - t0
        log.info(
            f"snapshot-load: from_pretrained in {self._snapshot_load_s * 1000:.0f}ms"
        )

    @modal.enter(snap=False)
    def move_to_gpu(self) -> None:
        init_sentry("generative_t2i")
        t0 = time.perf_counter()
        self.pipe.to("cuda")
        gpu_dt = time.perf_counter() - t0
        log.info(f"post-restore: pipe.to(cuda) in {gpu_dt * 1000:.0f}ms")

        # Built here (snap=False) so each container gets its own identity.
        self.runner = InferenceRunner(
            config="generative_t2i",
            gpu=GPU_NAME,
            scaledown_window_s=SCALEDOWN_WINDOW_S,
            log=log,
            cold={
                "snapshot_load": getattr(self, "_snapshot_load_s", 0.0),
                "to_cuda": gpu_dt,
            },
        )

    @modal.method()
    def generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        prompt = payload["prompt"]
        output_bucket = payload["output_bucket"]
        seed = payload.get("seed")
        num_inference_steps = payload.get("num_inference_steps") or 4
        guidance_scale = payload.get("guidance_scale", 0.0)
        width = payload.get("width") or 1024
        height = payload.get("height") or 1024

        with self.runner.start(payload) as run:
            log.info(
                f"[{run.request_id}] inference: start; prompt_len={len(prompt)} "
                f"steps={num_inference_steps} guidance={guidance_scale} seed={seed}"
            )
            run.batch(1)

            generator = None
            if seed is not None:
                generator = torch.Generator(device="cuda").manual_seed(int(seed))

            with run.phase("gpu"):
                out = self.pipe(
                    prompt=prompt,
                    guidance_scale=guidance_scale,
                    num_inference_steps=num_inference_steps,
                    width=width,
                    height=height,
                    generator=generator,
                )

            # Inlined upload — Sharp consumes bucket+key, so we build the key
            # locally instead of parsing it back out of upload_to_s3's URL.
            import boto3
            from botocore.config import Config as BotoConfig

            image_key = f"generative_t2i_results/{uuid.uuid4().hex}.png"
            with run.phase("upload"):
                result_image = out.images[0]
                buf = io.BytesIO()
                result_image.save(buf, format="PNG")
                png_bytes = buf.getvalue()
                boto3.client(
                    "s3",
                    aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
                    aws_secret_access_key=os.environ["S3_ACCESS_KEY_SECRET"],
                    endpoint_url=os.environ["S3_ENDPOINT"],
                    region_name=os.environ["S3_REGION"],
                    config=BotoConfig(
                        retries={"max_attempts": 5, "mode": "adaptive"}
                    ),
                ).put_object(Bucket=output_bucket, Key=image_key, Body=png_bytes)
            result_url = (
                f"{os.environ['S3_PUBLIC_BUCKETS_ENDPOINT']}/{output_bucket}/{image_key}"
            )
            log.info(
                f"[{run.request_id}] output "
                f"{result_image.width}x{result_image.height} "
                f"png_size={len(png_bytes)} bytes url={result_url}"
            )

            return run.finish(
                {
                    "result_url": result_url,
                    "image_bucket": output_bucket,
                    "image_key": image_key,
                    "width": result_image.width,
                    "height": result_image.height,
                    "seed": seed,
                }
            )
