"""Optimised FLUX.2 klein image-conditioned editing app.

Parallel branch to services/modal/flux/app.py — the production-grade
deployment with dynamic batching, async S3, parallel I/O within each
batch, and per-phase Prometheus metrics pushed to the Pushgateway.

Two endpoints exposed in this same app: one A10G (single input per
container) and one H100 (dynamic batching, max_batch_size=8). Same
code paths, different decorators. The A10G/H100 split is intentional
so per-config Modal billing stays separable for cost dashboards.

Key differences from the original `flux/app.py`:

  - `@modal.batched(...)` on H100 so N concurrent requests collapse
    into one GPU forward pass.
  - All non-GPU work parallelised via `aioboto3` (S3) + `asyncio.to_thread`
    (PIL encode/decode). Inside a batch the worst-case I/O time is the
    slowest single download, not the sum.
  - Per-phase metric pushes to the Pushgateway so Grafana panels can
    break out download / decode / pipe / encode / upload independently.
  - Cold-start phases are timed and pushed so the cold-start dashboard
    has real data, not just log lines.
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
    poll_function_call,
)


MODEL_REPO = "black-forest-labs/FLUX.2-klein-4B"
MODEL_LOCAL_DIR = f"{MODEL_DIR}/flux2-klein-4b"


log = configure_logging("flux_opt")
app, volume = make_app("demo-hub-flux-opt", "flux-models")


# Same image as the original flux app, plus aioboto3 for the async S3
# path and prometheus-client for the in-container metric push.
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
    import aioboto3
    import torch
    from diffusers import Flux2KleinPipeline
    from PIL import Image
    from prometheus_client import CollectorRegistry, Counter, Histogram, push_to_gateway


# ---------------------------------------------------------------------------
# Metrics — re-declared here with the same names as in
# services/common/observability/metrics.py so the Grafana panels work
# uniformly across scraped and pushed series.
# ---------------------------------------------------------------------------


def _build_metric_registry() -> tuple[
    "CollectorRegistry",
    "Histogram", "Histogram", "Histogram", "Histogram", "Counter",
]:
    reg = CollectorRegistry()
    io_h = Histogram(
        "demo_hub_flux_io_duration_seconds",
        "I/O phase wall-time inside generate().",
        ["config", "phase"],
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        registry=reg,
    )
    pipe_h = Histogram(
        "demo_hub_flux_pipe_duration_seconds",
        "GPU pipe(...) wall-time per batched call.",
        ["config"],
        buckets=(0.1, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0, 30.0),
        registry=reg,
    )
    batch_h = Histogram(
        "demo_hub_flux_batch_size",
        "Effective batch size at GPU dispatch time.",
        ["config"],
        buckets=(1, 2, 4, 8, 12, 16, 24, 32),
        registry=reg,
    )
    cold_h = Histogram(
        "demo_hub_flux_cold_start_duration_seconds",
        "Container lifecycle hook wall-time, by phase.",
        ["config", "phase"],
        buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0),
        registry=reg,
    )
    uptime_c = Counter(
        "demo_hub_flux_container_uptime_seconds_total",
        "Sum of container uptime seconds.",
        ["config", "gpu"],
        registry=reg,
    )
    return reg, io_h, pipe_h, batch_h, cold_h, uptime_c


def _push(registry: "CollectorRegistry", job: str, grouping_key: dict[str, str]) -> None:
    url = os.environ.get("PUSHGATEWAY_URL")
    if not url:
        return

    token = os.environ.get("PUSHGATEWAY_TOKEN")
    handler = None
    if token:
        import base64
        from urllib.request import Request, urlopen

        encoded = base64.b64encode(f"modal:{token}".encode()).decode()

        def _h(url, method, timeout, headers, data):  # noqa: ARG001
            req = Request(url, data=data, method=method)
            for k, v in headers:
                req.add_header(k, v)
            req.add_header("Authorization", f"Basic {encoded}")
            return urlopen(req, timeout=timeout)

        handler = _h

    try:
        if handler is not None:
            push_to_gateway(
                url, job=job, registry=registry,
                grouping_key=grouping_key, handler=handler, timeout=5.0,
            )
        else:
            push_to_gateway(
                url, job=job, registry=registry,
                grouping_key=grouping_key, timeout=5.0,
            )
    except Exception as e:
        log.warning(f"push_to_gateway({job}) failed: {e}")


# ---------------------------------------------------------------------------
# Preload — single-shot weight download. Same shape as flux/app.py since
# they share the volume.
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Inference class — base shared between A10G and H100 variants. The
# subclasses fix only the GPU + batched decorator.
# ---------------------------------------------------------------------------


class _FluxOptBase:
    CONFIG: str = "flux_opt"  # overridden by subclasses
    GPU_NAME: str = "A10G"

    @modal.enter(snap=True)
    def load_to_cpu(self) -> None:
        """CPU snapshot stage. GPU-agnostic — one snapshot serves both
        A10G and H100 variants.

        Runs ONCE at snapshot-build time, so it must not create any
        per-container state (identity, metric registry): that would get
        baked into the shared snapshot and reused by every restored
        container. All of that lives in move_to_gpu (snap=False)."""

        t0 = time.perf_counter()
        log.info("snapshot-load: load_to_cpu() begin")
        self.pipe = Flux2KleinPipeline.from_pretrained(
            MODEL_LOCAL_DIR,
            torch_dtype=torch.bfloat16,
        )
        # Stashed, not observed — the per-container registry doesn't exist
        # yet. move_to_gpu records this into it after restore.
        self._snapshot_load_cpu_s = time.perf_counter() - t0
        log.info(
            "snapshot-load: from_pretrained finished in "
            f"{self._snapshot_load_cpu_s * 1000:.0f}ms"
        )

    @modal.enter(snap=False)
    async def move_to_gpu(self) -> None:
        # Per-container identity + metric registry are created HERE
        # (snap=False, runs per restored container) — not in load_to_cpu.
        # Otherwise every container shares one snapshot-baked container_id
        # and their Pushgateway groups overwrite each other (uptime/cold
        # start get clobbered instead of summed).
        (
            self._reg,
            self._io_h,
            self._pipe_h,
            self._batch_h,
            self._cold_h,
            self._uptime_c,
        ) = _build_metric_registry()
        self._container_id = uuid.uuid4().hex[:8]
        self._cold_h.labels(config=self.CONFIG, phase="snapshot_load_cpu").observe(
            getattr(self, "_snapshot_load_cpu_s", 0.0)
        )

        t0 = time.perf_counter()
        log.info(f"[{self._container_id}] post-restore: move_to_gpu() begin")
        self.pipe.to("cuda")
        gpu_dt = time.perf_counter() - t0
        self._cold_h.labels(config=self.CONFIG, phase="to_cuda").observe(gpu_dt)

        # Build the shared aioboto3 client for the lifetime of this
        # container — one TCP+TLS-pooled session per container instead
        # of one per request.
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
        self._cold_h.labels(config=self.CONFIG, phase="s3_session_open").observe(s3_dt)

        self._container_started_at = time.monotonic()
        self._push_state()
        log.info(
            f"[{self._container_id}] post-restore: ready "
            f"(to_cuda={gpu_dt * 1000:.0f}ms, s3_open={s3_dt * 1000:.0f}ms)"
        )

    @modal.exit()
    async def cleanup(self) -> None:
        try:
            await self._s3_ctx.__aexit__(None, None, None)
        except Exception as e:
            log.warning(f"[{self._container_id}] s3 client close failed: {e}")

        uptime = time.monotonic() - self._container_started_at
        # Rough real-time cost proxy only. Modal billing (modal.billing
        # API/CLI + per-App tags) is the source of truth for actual $.
        self._uptime_c.labels(config=self.CONFIG, gpu=self.GPU_NAME).inc(uptime)
        self._push_state()

    def _push_state(self) -> None:
        """Push this container's whole cumulative registry under a stable
        per-container grouping key. Last-write-wins on the gateway then
        means "current cumulative state of this container" — one group
        per live container, bounded by container count (NOT batch count,
        which would leak a new group per inference forever)."""

        _push(
            self._reg,
            job="flux_opt",
            grouping_key={"config": self.CONFIG, "container_id": self._container_id},
        )

    async def _generate_batch(
        self, items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Shared body for both variants. Items can be a single-element
        list (A10G non-batched path) or N elements (H100 batched path).
        Modal's @modal.batched takes care of collecting; we just do the
        work."""

        batch_id = uuid.uuid4().hex[:6]
        log.info(
            f"[{self._container_id}/{batch_id}] generate: "
            f"items={len(items)} config={self.CONFIG}"
        )

        self._batch_h.labels(config=self.CONFIG).observe(len(items))

        # 1. Parallel S3 downloads.
        t_dl = time.perf_counter()

        async def _download(it: dict[str, Any]) -> bytes:
            resp = await self.s3.get_object(
                Bucket=it["image_bucket"], Key=it["image_key"]
            )
            return await resp["Body"].read()

        raws = await asyncio.gather(*[_download(it) for it in items])
        dl_dt = time.perf_counter() - t_dl
        self._io_h.labels(config=self.CONFIG, phase="download").observe(dl_dt)

        # 2. Parallel decode + EXIF + resize. CPU-bound, threadable.
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
        prep_dt = time.perf_counter() - t_prep
        self._io_h.labels(config=self.CONFIG, phase="decode").observe(prep_dt)

        # 3. Batched GPU forward. Blocking — by design, the event loop
        # has nothing else useful to do here.
        # One scalar drives the whole batched forward — diffusers can't
        # vary steps per sample. Take the max so a batched request never
        # silently runs fewer steps than asked (quality floor); guidance
        # is uniform (dispatch never varies it).
        steps = max(int(it.get("num_inference_steps") or 4) for it in items)
        t_pipe = time.perf_counter()
        out = self.pipe(
            image=inputs,
            prompt=[it["prompt"] for it in items],
            guidance_scale=items[0].get("guidance_scale", 1.0),
            num_inference_steps=steps,
        )
        pipe_dt = time.perf_counter() - t_pipe
        self._pipe_h.labels(config=self.CONFIG).observe(pipe_dt)
        log.info(
            f"[{self._container_id}/{batch_id}] gpu pipe: {pipe_dt * 1000:.0f}ms "
            f"({len(items)} images)"
        )

        # 4. Parallel PNG encode (threaded) + upload (async).
        t_up = time.perf_counter()

        async def _encode_upload(img: Image.Image, it: dict[str, Any]) -> str:
            def _encode(im: Image.Image) -> bytes:
                buf = io.BytesIO()
                im.save(buf, format="PNG")
                return buf.getvalue()

            png = await asyncio.to_thread(_encode, img)
            key = f"generative_results/{uuid4().hex}.png"
            await self.s3.put_object(
                Bucket=it["image_bucket"], Key=key, Body=png
            )
            return f"{os.environ['S3_PUBLIC_BUCKETS_ENDPOINT']}/{it['image_bucket']}/{key}"

        urls = await asyncio.gather(*[
            _encode_upload(img, it) for img, it in zip(out.images, items)
        ])
        up_dt = time.perf_counter() - t_up
        # Split: encode is roughly half, upload the other half — too
        # coarse for separation but the merged metric still tells the
        # right story for the dashboard.
        self._io_h.labels(config=self.CONFIG, phase="encode_upload").observe(up_dt)

        # Cumulative push on the stable per-container key (batch_id stays
        # a log field only — never a grouping key, or the gateway leaks a
        # group per batch).
        self._push_state()

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
    ],
)
class FluxOptH100(_FluxOptBase):
    CONFIG = "flux_opt_h100"
    GPU_NAME = "H100"

    @modal.batched(max_batch_size=8, wait_ms=200)
    async def generate(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return await self._generate_batch(items)


# ---------------------------------------------------------------------------
# Submit/poll endpoints — same pattern as the original flux app. One
# pair per class so dispatch hits the right variant.
# ---------------------------------------------------------------------------


@app.function(image=flux_thin_image, timeout=120)
@modal.fastapi_endpoint(method="POST", requires_proxy_auth=True)
def submit_a10g(payload: dict[str, Any]) -> dict[str, Any]:
    request_id = uuid.uuid4().hex[:8]
    err = _validate_payload(payload)
    if err is not None:
        log.warning(f"[{request_id}] submit_a10g: {err}")
        return {"error": err}

    call = FluxOptA10G().generate.spawn(_to_item(payload, request_id))
    return {"call_id": call.object_id, "request_id": request_id}


@app.function(image=flux_thin_image, timeout=120)
@modal.fastapi_endpoint(method="POST", requires_proxy_auth=True)
def poll_a10g(payload: dict[str, Any]) -> dict[str, Any]:
    return poll_function_call(payload.get("call_id"), log)


@app.function(image=flux_thin_image, timeout=120)
@modal.fastapi_endpoint(method="POST", requires_proxy_auth=True)
def submit_h100(payload: dict[str, Any]) -> dict[str, Any]:
    request_id = uuid.uuid4().hex[:8]
    err = _validate_payload(payload)
    if err is not None:
        log.warning(f"[{request_id}] submit_h100: {err}")
        return {"error": err}

    call = FluxOptH100().generate.spawn(_to_item(payload, request_id))
    return {"call_id": call.object_id, "request_id": request_id}


@app.function(image=flux_thin_image, timeout=120)
@modal.fastapi_endpoint(method="POST", requires_proxy_auth=True)
def poll_h100(payload: dict[str, Any]) -> dict[str, Any]:
    return poll_function_call(payload.get("call_id"), log)


def _validate_payload(payload: dict[str, Any]) -> str | None:
    if not payload.get("image_bucket") or not payload.get("image_key"):
        return "image_bucket and image_key are required"
    if not payload.get("prompt"):
        return "prompt is required"
    return None


def _to_item(payload: dict[str, Any], request_id: str) -> dict[str, Any]:
    return {
        "image_bucket": payload["image_bucket"],
        "image_key": payload["image_key"],
        "prompt": payload["prompt"],
        "guidance_scale": float(payload.get("guidance_scale", 1.0)),
        "num_inference_steps": int(payload.get("num_inference_steps", 4)),
        "max_side": int(payload.get("max_side", 1024)),
        "request_id": request_id,
    }
