"""Optimised FLUX.2-klein image-conditioned editing (A10G + H100).

Endpoint-less: invoked by name through the gateway. Dynamic batching on
H100, async S3 + parallel per-batch I/O, per-phase metrics via InferenceMetrics.
"""

from __future__ import annotations

import asyncio
import io
import os
import time
import uuid
from typing import Any
from uuid import uuid4

import modal

from common.lib import (
    MODEL_DIR,
    bake_exif_orientation,
    configure_logging,
    make_app,
)
from common.metrics import InferenceMetrics
from common.sentry import init_sentry


MODEL_REPO = "black-forest-labs/FLUX.2-klein-4B"
MODEL_LOCAL_DIR = f"{MODEL_DIR}/flux2-klein-4b"


log = configure_logging("flux_opt")
app, volume = make_app("demo-hub-flux-opt", "flux-models")


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
        "aioboto3==13.2.0",
        "prometheus-client==0.20.0",
        "sentry-sdk>=2.42.0",
    )
    .env(
        {
            "HF_HUB_ENABLE_HF_TRANSFER": "1",
            "HF_HOME": "/root/.cache/huggingface",
            "TRANSFORMERS_OFFLINE": "0",
        }
    )
    .add_local_python_source("common.lib", "common.metrics", "common.sentry")
)


with flux_image.imports():
    import aioboto3
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
    from huggingface_hub import snapshot_download

    log.info(f"preload: starting; repo={MODEL_REPO} -> {MODEL_LOCAL_DIR}")
    os.makedirs(MODEL_LOCAL_DIR, exist_ok=True)
    snapshot_download(
        repo_id=MODEL_REPO,
        local_dir=MODEL_LOCAL_DIR,
        token=os.environ.get("HF_TOKEN"),
        max_workers=8,
    )
    volume.commit()
    return MODEL_LOCAL_DIR


class _FluxOptBase:
    CONFIG: str = "flux_opt"
    GPU_NAME: str = "A10G"

    @modal.enter(snap=True)
    def load_to_cpu(self) -> None:
        """CPU snapshot stage (runs once at build time). No per-container
        state here — it'd bake into the snapshot; see move_to_gpu."""

        t0 = time.perf_counter()
        log.info("snapshot-load: load_to_cpu() begin")
        self.pipe = Flux2KleinPipeline.from_pretrained(
            MODEL_LOCAL_DIR,
            torch_dtype=torch.bfloat16,
        )
        self._snapshot_load_cpu_s = time.perf_counter() - t0
        log.info(
            "snapshot-load: from_pretrained finished in "
            f"{self._snapshot_load_cpu_s * 1000:.0f}ms"
        )

    @modal.enter(snap=False)
    async def move_to_gpu(self) -> None:
        init_sentry(self.CONFIG)
        # Built here (snap=False) so each container gets its own identity.
        self.m = InferenceMetrics(self.CONFIG, self.GPU_NAME)
        self.m.cold_start(
            "snapshot_load_cpu", getattr(self, "_snapshot_load_cpu_s", 0.0)
        )

        t0 = time.perf_counter()
        log.info(f"[{self.m.container_id}] post-restore: move_to_gpu() begin")
        self.pipe.to("cuda")
        gpu_dt = time.perf_counter() - t0
        self.m.cold_start("to_cuda", gpu_dt)

        t1 = time.perf_counter()
        self._s3_session = aioboto3.Session()
        self._s3_ctx = self._s3_session.client(
            "s3",
            aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["S3_ACCESS_KEY_SECRET"],
            endpoint_url=os.environ["S3_ENDPOINT"],
            region_name=os.environ["S3_REGION"],
        )
        self.s3 = await self._s3_ctx.__aenter__()
        s3_dt = time.perf_counter() - t1
        self.m.cold_start("s3_session_open", s3_dt)
        self.m.push()
        log.info(
            f"[{self.m.container_id}] post-restore: ready "
            f"(to_cuda={gpu_dt * 1000:.0f}ms, s3_open={s3_dt * 1000:.0f}ms)"
        )

    @modal.exit()
    async def cleanup(self) -> None:
        try:
            await self._s3_ctx.__aexit__(None, None, None)
        except Exception as e:
            log.warning(f"[{self.m.container_id}] s3 client close failed: {e}")
        # Rough real-time cost proxy; Modal billing is source of truth for $.
        self.m.push_uptime()

    async def _generate_batch(
        self, items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        batch_id = uuid.uuid4().hex[:6]
        log.info(
            f"[{self.m.container_id}/{batch_id}] generate: "
            f"items={len(items)} config={self.CONFIG}"
        )
        self.m.batch(len(items))

        t_dl = time.perf_counter()

        async def _download(it: dict[str, Any]) -> bytes:
            resp = await self.s3.get_object(
                Bucket=it["image_bucket"], Key=it["image_key"]
            )
            return await resp["Body"].read()

        raws = await asyncio.gather(*[_download(it) for it in items])
        self.m.observe("download", time.perf_counter() - t_dl)

        t_prep = time.perf_counter()

        def _prep(raw: bytes, max_side: int) -> Image.Image:
            oriented = bake_exif_orientation(raw)
            img = Image.open(io.BytesIO(oriented)).convert("RGB")
            w, h = img.size
            s = max_side / max(w, h)
            return (
                img.resize((int(w * s), int(h * s)), Image.LANCZOS) if s < 1 else img
            )

        inputs = await asyncio.gather(*[
            asyncio.to_thread(_prep, raw, it.get("max_side", 1024))
            for raw, it in zip(raws, items)
        ])
        self.m.observe("decode", time.perf_counter() - t_prep)

        # diffusers takes one scalar per batch; max() so nobody loses steps
        steps = max(int(it.get("num_inference_steps") or 4) for it in items)
        t_pipe = time.perf_counter()
        out = self.pipe(
            image=inputs,
            prompt=[it["prompt"] for it in items],
            guidance_scale=items[0].get("guidance_scale", 1.0),
            num_inference_steps=steps,
        )
        pipe_dt = time.perf_counter() - t_pipe
        self.m.observe("gpu", pipe_dt)
        log.info(
            f"[{self.m.container_id}/{batch_id}] gpu pipe: {pipe_dt * 1000:.0f}ms "
            f"({len(items)} images)"
        )

        t_up = time.perf_counter()

        async def _encode_upload(img: Image.Image, it: dict[str, Any]) -> str:
            def _encode(im: Image.Image) -> bytes:
                buf = io.BytesIO()
                im.save(buf, format="PNG")
                return buf.getvalue()

            png = await asyncio.to_thread(_encode, img)
            key = f"generative_results/{uuid4().hex}.png"
            await self.s3.put_object(Bucket=it["image_bucket"], Key=key, Body=png)
            return f"{os.environ['S3_PUBLIC_BUCKETS_ENDPOINT']}/{it['image_bucket']}/{key}"

        urls = await asyncio.gather(*[
            _encode_upload(img, it) for img, it in zip(out.images, items)
        ])
        self.m.observe("encode_upload", time.perf_counter() - t_up)
        self.m.push()

        return [
            {"result_url": u, "width": img.width, "height": img.height}
            for u, img in zip(urls, out.images)
        ]


@app.cls(
    image=flux_image,
    gpu="A10G",
    volumes={MODEL_DIR: volume},
    scaledown_window=30,
    timeout=600,
    enable_memory_snapshot=True,
    secrets=[
        modal.Secret.from_name("supabase-s3"),
        modal.Secret.from_name("pushgateway"),
        modal.Secret.from_name("sentry"),
    ],
)
@modal.concurrent(max_inputs=4)
class FluxOptA10G(_FluxOptBase):
    CONFIG = "flux_opt_a10g"
    GPU_NAME = "A10G"

    @modal.method()
    async def generate(self, item: dict[str, Any]) -> dict[str, Any]:
        results = await self._generate_batch([item])
        return results[0]


@app.cls(
    image=flux_image,
    gpu="H100",
    volumes={MODEL_DIR: volume},
    scaledown_window=30,
    timeout=600,
    enable_memory_snapshot=True,
    secrets=[
        modal.Secret.from_name("supabase-s3"),
        modal.Secret.from_name("pushgateway"),
        modal.Secret.from_name("sentry"),
    ],
)
class FluxOptH100(_FluxOptBase):
    CONFIG = "flux_opt_h100"
    GPU_NAME = "H100"

    @modal.batched(max_batch_size=8, wait_ms=200)
    async def generate(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return await self._generate_batch(items)
