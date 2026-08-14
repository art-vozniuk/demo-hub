"""Thin async clients for Modal-hosted inference endpoints.

Every Modal app exposes the same shape — a `submit` endpoint that spawns
a FunctionCall and returns a call_id, and a `poll` endpoint dispatch
polls until the call resolves. Both endpoints are gated by Modal's
proxy-auth; shared header + timeout logic lives in `_post_to_modal`,
shared submit+poll cadence lives in `_submit_and_poll`.

A submit+poll pair (rather than a sync POST) is mandatory for any app
whose cold start can outrun Modal's ~60s sync gateway cap. SHARP needs
that; FLUX runs fast warm but its cold start has hit the cap too. One
flow for both keeps the dispatch surface uniform.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

import httpx

from services.common.constants import GPU_HOURLY_USD
from services.common.observability.metrics import (
    estimated_gpu_cost_usd_total,
    estimated_gpu_seconds_total,
    inference_batch_size,
    inference_cold_start_duration_seconds,
    inference_phase_duration_seconds,
    inference_requests_total,
    modal_call_duration_seconds,
    modal_call_requests_total,
    modal_call_retries_total,
    modal_overhead_seconds,
)
from services.common.observability.tracing import span, trace_headers
from services.dispatch.app.config import config

log = logging.getLogger(__name__)


class ModalInferenceError(RuntimeError):
    pass


# TEMPORARY: in-place retry + shared client live here while we decide on
# a sane home in services/common (one module owning retry policy + a
# shared httpx pool for every outbound HTTP integration: Modal, S3
# presign refresh, future webhooks, etc.). Extract this whole block once
# the second consumer of "retry an outbound POST against a flaky cloud
# gateway" shows up; until then a copy-pasted version here is cheaper
# than a half-designed abstraction.

_client: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()


async def _get_client() -> httpx.AsyncClient:
    """One client per worker process; pool reuse is what kills the
    handshake-churn that a fresh client-per-call was costing us
    (256 prefetch × 1 poll/s = 256 TLS handshakes/s otherwise)."""

    global _client
    if _client is not None:
        return _client

    async with _client_lock:
        if _client is None:
            timeout = httpx.Timeout(config.MODAL_REQUEST_TIMEOUT_SECONDS, connect=10.0)
            limits = httpx.Limits(
                max_keepalive_connections=config.MODAL_HTTP_POOL_KEEPALIVE,
                max_connections=config.MODAL_HTTP_POOL_MAX,
            )
            _client = httpx.AsyncClient(timeout=timeout, limits=limits)
            log.info(
                "modal_client: created shared httpx.AsyncClient "
                f"(keepalive={config.MODAL_HTTP_POOL_KEEPALIVE}, "
                f"max={config.MODAL_HTTP_POOL_MAX}, "
                f"timeout={config.MODAL_REQUEST_TIMEOUT_SECONDS}s)"
            )
        return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _is_retryable_status(status_code: int) -> bool:
    # 5xx + 408 + 429 are transient. 4xx (auth, bad request) are ours
    # and would just loop forever.
    return status_code >= 500 or status_code in (408, 429)


async def _backoff_sleep(attempt: int) -> None:
    base = config.MODAL_RETRY_BASE_DELAY_MS / 1000.0
    cap = config.MODAL_RETRY_MAX_DELAY_MS / 1000.0
    # Decorrelated jitter: spread out simultaneous retries so 256
    # concurrent in-flight requests don't ping Modal in lockstep after a blip.
    delay = min(cap, base * (2**attempt)) * (0.5 + random.random() * 0.5)
    await asyncio.sleep(delay)


async def _post_to_modal(
    endpoint_label: str,
    url: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """POST with shared-pool client + bounded retry on transient errors.

    Retries are local — they never escalate to RabbitMQ requeue. A
    transient 502 from Modal-gateway costs a few hundred ms of backoff;
    a requeue costs a full new Modal call + cold start + GPU billing."""

    if not url:
        raise ModalInferenceError(
            f"{endpoint_label} not configured. "
            "See services/modal/README.md for deployment steps."
        )

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if config.MODAL_PROXY_AUTH_TOKEN_ID and config.MODAL_PROXY_AUTH_TOKEN_SECRET:
        headers["Modal-Key"] = config.MODAL_PROXY_AUTH_TOKEN_ID
        headers["Modal-Secret"] = config.MODAL_PROXY_AUTH_TOKEN_SECRET

    client = await _get_client()
    last_err: Exception | None = None
    t0 = time.monotonic()

    for attempt in range(config.MODAL_RETRY_MAX_ATTEMPTS):
        try:
            resp = await client.post(url, headers=headers, json=payload)

            if resp.status_code < 400:
                modal_call_requests_total.labels(
                    endpoint=endpoint_label, status="ok"
                ).inc()
                modal_call_duration_seconds.labels(endpoint=endpoint_label).observe(
                    time.monotonic() - t0
                )
                try:
                    return resp.json()
                except ValueError as e:
                    raise ModalInferenceError(f"Modal returned non-JSON body: {e}")

            if not _is_retryable_status(resp.status_code):
                # 4xx — our bug; no point retrying.
                modal_call_requests_total.labels(
                    endpoint=endpoint_label, status="4xx"
                ).inc()
                raise ModalInferenceError(
                    f"Modal returned {resp.status_code}: {resp.text[:500]}"
                )

            last_err = ModalInferenceError(
                f"Modal transient {resp.status_code}: {resp.text[:200]}"
            )
            modal_call_retries_total.labels(
                endpoint=endpoint_label, reason=f"http_{resp.status_code}"
            ).inc()
            log.warning(
                f"{endpoint_label}: transient HTTP {resp.status_code} "
                f"(attempt {attempt + 1}/{config.MODAL_RETRY_MAX_ATTEMPTS}); "
                f"will retry"
            )
        except (
            httpx.ConnectError,
            httpx.ReadError,
            httpx.WriteError,
            httpx.TimeoutException,
            httpx.RemoteProtocolError,
        ) as e:
            last_err = e
            modal_call_retries_total.labels(
                endpoint=endpoint_label, reason=type(e).__name__
            ).inc()
            log.warning(
                f"{endpoint_label}: transient network error "
                f"{type(e).__name__} (attempt {attempt + 1}/"
                f"{config.MODAL_RETRY_MAX_ATTEMPTS}): {e}; will retry"
            )

        if attempt < config.MODAL_RETRY_MAX_ATTEMPTS - 1:
            await _backoff_sleep(attempt)

    modal_call_requests_total.labels(endpoint=endpoint_label, status="exhausted").inc()
    raise ModalInferenceError(
        f"{endpoint_label}: exhausted {config.MODAL_RETRY_MAX_ATTEMPTS} "
        f"retry attempts; last_err={last_err!r}"
    )


async def _submit_and_poll(
    label: str,
    submit_url: str | None,
    poll_url: str | None,
    submit_url_label: str,
    poll_url_label: str,
    payload: dict[str, Any],
    deadline_seconds: int | None = None,
) -> dict[str, Any]:
    """POST to /submit, then /poll on a fixed cadence until done.

    `deadline_seconds` defaults to the standard pipeline deadline; pipelines
    whose runtime scales with input size pass the longer one. It must match the
    timeout the target Modal function declares, or one side gives up first and
    the other keeps burning a container.
    """

    with span("modal.submit", label):
        submit_resp = await _post_to_modal(submit_url_label, submit_url, payload)
    if "error" in submit_resp:
        raise ModalInferenceError(
            f"Modal {label} submit failed: {submit_resp['error']}"
        )
    call_id = submit_resp.get("call_id")
    request_id = submit_resp.get("request_id")
    if not call_id:
        raise ModalInferenceError(
            f"Modal {label} submit returned no call_id; body={submit_resp}"
        )

    budget = deadline_seconds or config.MODAL_PIPELINE_DEADLINE_SECONDS
    log.info(
        f"[{request_id}] {label} submit ok; polling call_id={call_id} "
        f"(deadline {budget}s)"
    )
    deadline = time.monotonic() + budget
    poll_count = 0
    with span("modal.poll", label) as poll_span:
        while True:
            if time.monotonic() > deadline:
                raise ModalInferenceError(
                    f"Modal {label} poll timed out after {budget}s; call_id={call_id}"
                )

            poll_resp = await _post_to_modal(
                poll_url_label,
                poll_url,
                {"call_id": call_id},
            )
            poll_count += 1
            status = poll_resp.get("status")
            if status == "done":
                log.info(
                    f"[{request_id}] {label} done after {poll_count} polls; "
                    f"call_id={call_id}"
                )
                if poll_span is not None:
                    poll_span.set_data("polls", poll_count)
                return poll_resp["result"]
            if status in ("failed", "expired", "error"):
                raise ModalInferenceError(
                    f"Modal {label} poll status={status}; call_id={call_id} "
                    f"error={poll_resp.get('error')}"
                )
            await asyncio.sleep(config.MODAL_POLL_INTERVAL_SECONDS)


def _record_inference_obs(
    model: str, result: dict[str, Any], call_wall_s: float
) -> None:
    """Record the `_obs` block a Modal container attached to its response —
    the only place inference metrics get recorded (containers aren't scraped)."""

    obs = result.pop("_obs", None)
    if not isinstance(obs, dict):
        return

    # Gateway model name == pipeline_name: one label namespace in Grafana.
    config_label = model
    gpu = obs.get("gpu", "unknown")
    total_s = float(obs.get("total_s", 0.0))
    cold = obs.get("cold") or None

    inference_requests_total.labels(
        config=config_label, cold="true" if cold else "false"
    ).inc()

    for phase, seconds in (obs.get("timings") or {}).items():
        inference_phase_duration_seconds.labels(
            config=config_label, phase=phase
        ).observe(float(seconds))

    cold_in_call_s = 0.0
    if cold:
        for phase, seconds in cold.items():
            inference_cold_start_duration_seconds.labels(
                config=config_label, phase=phase
            ).observe(float(seconds))
            # snapshot_load happened at snapshot creation, not in this call.
            if phase != "snapshot_load":
                cold_in_call_s += float(seconds)

    batch = obs.get("batch_size")
    if batch:
        inference_batch_size.labels(config=config_label).observe(int(batch))

    overhead = max(call_wall_s - total_s - cold_in_call_s, 0.0)
    modal_overhead_seconds.labels(config=config_label).observe(overhead)

    # Estimate: work + (on cold start) spin-up + idle scaledown tail.
    billed_s = total_s + cold_in_call_s
    if cold:
        billed_s += float(obs.get("scaledown_window_s", 0.0))
    estimated_gpu_seconds_total.labels(config=config_label, gpu=gpu).inc(billed_s)
    rate = GPU_HOURLY_USD.get(gpu)
    if rate is not None:
        estimated_gpu_cost_usd_total.labels(config=config_label, gpu=gpu).inc(
            billed_s * rate / 3600.0
        )


# Every pipeline goes through the shared Modal web gateway; the target app +
# class is chosen server-side by payload["model"] (see gateway ROUTES).
async def _invoke_gateway(
    model: str,
    payload: dict[str, Any],
    deadline_seconds: int | None = None,
) -> dict[str, Any]:
    from services.common.logging.config import context_pipeline_id

    # Sentry headers let the container resume the pipeline's trace;
    # pipeline_id doubles as the container-side request id.
    enriched = {**payload, "model": model, **trace_headers()}
    pipeline_id = context_pipeline_id.get()
    if pipeline_id:
        enriched.setdefault("pipeline_id", pipeline_id)

    t0 = time.monotonic()
    result = await _submit_and_poll(
        label=model,
        submit_url=config.MODAL_GATEWAY_SUBMIT_URL,
        poll_url=config.MODAL_GATEWAY_POLL_URL,
        submit_url_label="MODAL_GATEWAY_SUBMIT_URL",
        poll_url_label="MODAL_GATEWAY_POLL_URL",
        payload=enriched,
        deadline_seconds=deadline_seconds,
    )
    try:
        _record_inference_obs(model, result, time.monotonic() - t0)
    except Exception:
        log.warning("failed to record inference observability block", exc_info=True)
    return result


async def invoke_generative_editing(payload: dict[str, Any]) -> dict[str, Any]:
    return await _invoke_gateway("generative_editing", payload)


async def invoke_generative_editing_custom(payload: dict[str, Any]) -> dict[str, Any]:
    return await _invoke_gateway("generative_editing_custom", payload)


async def invoke_sharp(payload: dict[str, Any]) -> dict[str, Any]:
    return await _invoke_gateway("sharp", payload)


async def invoke_trellis(payload: dict[str, Any]) -> dict[str, Any]:
    return await _invoke_gateway("trellis", payload)


# Both transcriber steps run to the long deadline: transcription because its
# runtime scales with audio length, extraction because demuxing a multi-GB
# video is bounded by download + disk, not by a model.
async def invoke_transcriber(payload: dict[str, Any]) -> dict[str, Any]:
    return await _invoke_gateway(
        "transcriber",
        payload,
        deadline_seconds=config.MODAL_LONG_PIPELINE_DEADLINE_SECONDS,
    )


async def invoke_transcriber_extract(payload: dict[str, Any]) -> dict[str, Any]:
    return await _invoke_gateway(
        "transcriber_extract",
        payload,
        deadline_seconds=config.MODAL_LONG_PIPELINE_DEADLINE_SECONDS,
    )


async def invoke_generative_t2i(payload: dict[str, Any]) -> dict[str, Any]:
    return await _invoke_gateway("generative_t2i", payload)


async def invoke_flux_opt_a10g(payload: dict[str, Any]) -> dict[str, Any]:
    return await _invoke_gateway("flux_opt_a10g", payload)


async def invoke_flux_opt_h100(payload: dict[str, Any]) -> dict[str, Any]:
    return await _invoke_gateway("flux_opt_h100", payload)
