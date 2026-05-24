"""FLUX.1 [schnell] text-to-image on L40S."""

from __future__ import annotations

import io
import os
import time
import uuid
from typing import Any

import modal

from common.lib import (
    MODEL_DIR,
    configure_logging,
    make_app,
    poll_function_call,
)


MODEL_REPO = "black-forest-labs/FLUX.1-schnell"
MODEL_LOCAL_DIR = f"{MODEL_DIR}/flux1-schnell"


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
    )
    .env(
        {
            "HF_HUB_ENABLE_HF_TRANSFER": "1",
            "HF_HOME": "/root/.cache/huggingface",
            "TRANSFORMERS_OFFLINE": "0",
        }
    )
    .add_local_python_source("common.lib")
)


flux_thin_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "fastapi[standard]==0.115.6",
        "pydantic==2.10.3",
    )
    .add_local_python_source("common.lib")
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
    # schnell bfloat16 weights are ~24GB — A10G's 22GB OOMs on .to("cuda").
    gpu="L40S",
    volumes={MODEL_DIR: volume},
    scaledown_window=10,
    timeout=600,
    enable_memory_snapshot=True,
    secrets=[modal.Secret.from_name("supabase-s3")],
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
        load_ms = (time.perf_counter() - t0) * 1000
        log.info(f"snapshot-load: from_pretrained in {load_ms:.0f}ms")

    @modal.enter(snap=False)
    def move_to_gpu(self) -> None:
        t0 = time.perf_counter()
        self.pipe.to("cuda")
        ms = (time.perf_counter() - t0) * 1000
        log.info(f"post-restore: pipe.to(cuda) in {ms:.0f}ms")

    @modal.method()
    def generate(
        self,
        prompt: str,
        request_id: str,
        output_bucket: str,
        seed: int | None = None,
        num_inference_steps: int = 4,
        guidance_scale: float = 0.0,
        width: int = 1024,
        height: int = 1024,
    ) -> dict[str, Any]:
        log.info(
            f"[{request_id}] inference: start; prompt_len={len(prompt)} "
            f"steps={num_inference_steps} guidance={guidance_scale} seed={seed}"
        )
        t0 = time.perf_counter()

        generator = None
        if seed is not None:
            generator = torch.Generator(device="cuda").manual_seed(int(seed))

        t_inf = time.perf_counter()
        log.info(
            f"[{request_id}] inference: pipe(...) call begin; "
            f"prompt={prompt[:80]!r}{'...' if len(prompt) > 80 else ''}"
        )
        out = self.pipe(
            prompt=prompt,
            guidance_scale=guidance_scale,
            num_inference_steps=num_inference_steps,
            width=width,
            height=height,
            generator=generator,
        )
        inference_ms = (time.perf_counter() - t_inf) * 1000
        log.info(
            f"[{request_id}] inference: pipe(...) returned in {inference_ms:.0f}ms"
        )

        result_image = out.images[0]
        buf = io.BytesIO()
        result_image.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        # Inlined upload — Sharp consumes bucket+key, so we build the key locally
        # instead of parsing it back out of common.lib.upload_to_s3's URL.
        import boto3
        from botocore.config import Config as BotoConfig

        image_key = f"generative_t2i_results/{uuid.uuid4().hex}.png"
        t_up = time.perf_counter()
        boto3.client(
            "s3",
            aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["S3_ACCESS_KEY_SECRET"],
            endpoint_url=os.environ["S3_ENDPOINT"],
            region_name=os.environ["S3_REGION"],
            config=BotoConfig(retries={"max_attempts": 5, "mode": "adaptive"}),
        ).put_object(Bucket=output_bucket, Key=image_key, Body=png_bytes)
        result_url = f"{os.environ['S3_PUBLIC_BUCKETS_ENDPOINT']}/{output_bucket}/{image_key}"
        upload_ms = (time.perf_counter() - t_up) * 1000

        total_ms = (time.perf_counter() - t0) * 1000
        log.info(
            f"[{request_id}] inference: done; output "
            f"{result_image.width}x{result_image.height} "
            f"png_size={len(png_bytes)} bytes "
            f"inference_ms={inference_ms:.0f} upload_ms={upload_ms:.0f} "
            f"total_ms={total_ms:.0f} url={result_url}"
        )

        return {
            "result_url": result_url,
            "image_bucket": output_bucket,
            "image_key": image_key,
            "width": result_image.width,
            "height": result_image.height,
            "seed": seed,
        }


@app.function(image=flux_thin_image, timeout=120)
@modal.fastapi_endpoint(method="POST", requires_proxy_auth=True)
def submit(payload: dict[str, Any]) -> dict[str, Any]:
    request_id = uuid.uuid4().hex[:8]
    prompt = payload.get("prompt")
    log.info(
        f"[{request_id}] submit: received; prompt_len={len(prompt) if prompt else 0}"
    )
    if not prompt:
        log.warning(f"[{request_id}] submit: missing prompt")
        return {"error": "prompt is required"}

    output_bucket = payload.get("output_bucket")
    if not output_bucket:
        log.warning(f"[{request_id}] submit: missing output_bucket")
        return {"error": "output_bucket is required"}

    seed_raw = payload.get("seed")
    seed = int(seed_raw) if seed_raw is not None else None
    num_inference_steps = int(payload.get("num_inference_steps", 4))
    guidance_scale = float(payload.get("guidance_scale", 0.0))
    width = int(payload.get("width", 1024))
    height = int(payload.get("height", 1024))

    call = FluxT2IInference().generate.spawn(
        request_id=request_id,
        prompt=prompt,
        output_bucket=output_bucket,
        seed=seed,
        num_inference_steps=num_inference_steps,
        guidance_scale=guidance_scale,
        width=width,
        height=height,
    )
    log.info(f"[{request_id}] submit: spawned call_id={call.object_id}")
    return {"call_id": call.object_id, "request_id": request_id}


@app.function(image=flux_thin_image, timeout=120)
@modal.fastapi_endpoint(method="POST", requires_proxy_auth=True)
def poll(payload: dict[str, Any]) -> dict[str, Any]:
    return poll_function_call(payload.get("call_id"), log)
