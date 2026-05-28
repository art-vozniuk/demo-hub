"""Mock Modal app for cheap bench iteration.

CPU-only container that sleeps a deterministic amount of time and
returns a stub `result_url`. Used by the bench coordinator's
MOCK_MODAL tier — validates the full submit/poll + Pushgateway path
end-to-end without paying for a GPU.

Container cost when this is hit: a few cents per hour of warm uptime,
which means hundreds of bench iterations land for less than a dollar
total. The deployed cost is ~0 between bench runs because Modal scales
down automatically (scaledown_window=10).
"""

from __future__ import annotations

import asyncio
import os
import random
import time
import uuid
from typing import Any

import modal

from common.lib import configure_logging, make_app, poll_function_call


log = configure_logging("flux_mock")
app, volume = make_app("demo-hub-flux-mock", "flux-models")


mock_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "fastapi[standard]==0.115.6",
        "pydantic==2.10.3",
        "prometheus-client==0.20.0",
    )
    .add_local_python_source("common.lib")
)


with mock_image.imports():
    from prometheus_client import CollectorRegistry, Histogram, push_to_gateway


def _push(registry, job: str, grouping_key: dict[str, str]) -> None:
    url = os.environ.get("PUSHGATEWAY_URL")
    if not url:
        return

    token = os.environ.get("PUSHGATEWAY_TOKEN")
    handler = None
    if token:
        import base64
        from urllib.request import Request, urlopen

        encoded = base64.b64encode(f"bench:{token}".encode()).decode()

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


@app.cls(
    image=mock_image,
    cpu=1.0,
    memory=512,
    scaledown_window=10,
    timeout=300,
)
class FluxMockInference:
    @modal.enter()
    def setup(self) -> None:
        self._container_id = uuid.uuid4().hex[:8]
        log.info(f"[{self._container_id}] mock: setup")

    @modal.method()
    async def generate(self, item: dict[str, Any]) -> dict[str, Any]:
        request_id = item.get("request_id", uuid.uuid4().hex[:8])
        log.info(f"[{request_id}] mock: generate begin")

        reg = CollectorRegistry()
        h = Histogram(
            "demo_hub_flux_pipe_duration_seconds",
            "GPU pipe(...) wall-time per batched call (mocked).",
            ["config"],
            buckets=(0.5, 1.0, 2.0, 5.0),
            registry=reg,
        )

        t0 = time.perf_counter()
        # Deterministic-ish sleep with mild jitter — mirrors real GPU
        # variance enough that the bench coordinator's pacing logic
        # behaves the same as it would against a real backend.
        delay = random.uniform(0.8, 1.5)
        await asyncio.sleep(delay)
        h.labels(config="flux_modal_mock").observe(time.perf_counter() - t0)

        _push(
            reg,
            job="flux_mock_generate",
            grouping_key={
                "config": "flux_modal_mock",
                "container_id": self._container_id,
                "request_id": request_id,
            },
        )

        log.info(f"[{request_id}] mock: generate done in {delay * 1000:.0f}ms")
        return {
            "result_url": f"stub://flux-modal-mock/{request_id}",
            "width": 1024,
            "height": 1024,
        }


@app.function(image=mock_image, timeout=120)
@modal.fastapi_endpoint(method="POST", requires_proxy_auth=True)
def submit(payload: dict[str, Any]) -> dict[str, Any]:
    request_id = uuid.uuid4().hex[:8]
    call = FluxMockInference().generate.spawn({
        **payload, "request_id": request_id,
    })
    log.info(f"[{request_id}] mock submit: spawned {call.object_id}")
    return {"call_id": call.object_id, "request_id": request_id}


@app.function(image=mock_image, timeout=120)
@modal.fastapi_endpoint(method="POST", requires_proxy_auth=True)
def poll(payload: dict[str, Any]) -> dict[str, Any]:
    return poll_function_call(payload.get("call_id"), log)
