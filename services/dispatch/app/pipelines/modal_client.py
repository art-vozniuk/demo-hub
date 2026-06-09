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

from services.common.observability.metrics import (
    modal_call_duration_seconds,
    modal_call_requests_total,
    modal_call_retries_total,
)
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
) -> dict[str, Any]:
    """POST to /submit, then /poll on a fixed cadence until done."""

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

    log.info(f"[{request_id}] {label} submit ok; polling call_id={call_id}")
    deadline = time.monotonic() + config.MODAL_PIPELINE_DEADLINE_SECONDS
    poll_count = 0
    while True:
        if time.monotonic() > deadline:
            raise ModalInferenceError(
                f"Modal {label} poll timed out after "
                f"{config.MODAL_PIPELINE_DEADLINE_SECONDS}s; call_id={call_id}"
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
            return poll_resp["result"]
        if status in ("failed", "expired", "error"):
            raise ModalInferenceError(
                f"Modal {label} poll status={status}; call_id={call_id} "
                f"error={poll_resp.get('error')}"
            )
        await asyncio.sleep(config.MODAL_POLL_INTERVAL_SECONDS)


async def invoke_generative_editing(payload: dict[str, Any]) -> dict[str, Any]:
    return await _submit_and_poll(
        label="generative_editing",
        submit_url=config.MODAL_GENERATIVE_SUBMIT_URL,
        poll_url=config.MODAL_GENERATIVE_POLL_URL,
        submit_url_label="MODAL_GENERATIVE_SUBMIT_URL",
        poll_url_label="MODAL_GENERATIVE_POLL_URL",
        payload=payload,
    )


async def invoke_generative_editing_custom(
    payload: dict[str, Any],
) -> dict[str, Any]:
    # Same Modal app as generative_editing — the only difference at the
    # boundary is that the prompt arrives free-form from the user instead
    # of being resolved from a preset on core.
    return await _submit_and_poll(
        label="generative_editing_custom",
        submit_url=config.MODAL_GENERATIVE_SUBMIT_URL,
        poll_url=config.MODAL_GENERATIVE_POLL_URL,
        submit_url_label="MODAL_GENERATIVE_SUBMIT_URL",
        poll_url_label="MODAL_GENERATIVE_POLL_URL",
        payload=payload,
    )


async def invoke_sharp(payload: dict[str, Any]) -> dict[str, Any]:
    return await _submit_and_poll(
        label="sharp",
        submit_url=config.MODAL_SHARP_SUBMIT_URL,
        poll_url=config.MODAL_SHARP_POLL_URL,
        submit_url_label="MODAL_SHARP_SUBMIT_URL",
        poll_url_label="MODAL_SHARP_POLL_URL",
        payload=payload,
    )


async def invoke_trellis(payload: dict[str, Any]) -> dict[str, Any]:
    return await _submit_and_poll(
        label="trellis",
        submit_url=config.MODAL_TRELLIS_SUBMIT_URL,
        poll_url=config.MODAL_TRELLIS_POLL_URL,
        submit_url_label="MODAL_TRELLIS_SUBMIT_URL",
        poll_url_label="MODAL_TRELLIS_POLL_URL",
        payload=payload,
    )


async def invoke_generative_t2i(payload: dict[str, Any]) -> dict[str, Any]:
    return await _submit_and_poll(
        label="generative_t2i",
        submit_url=config.MODAL_GENERATIVE_T2I_SUBMIT_URL,
        poll_url=config.MODAL_GENERATIVE_T2I_POLL_URL,
        submit_url_label="MODAL_GENERATIVE_T2I_SUBMIT_URL",
        poll_url_label="MODAL_GENERATIVE_T2I_POLL_URL",
        payload=payload,
    )


async def invoke_flux_opt_a10g(payload: dict[str, Any]) -> dict[str, Any]:
    return await _submit_and_poll(
        label="flux_opt_a10g",
        submit_url=config.MODAL_FLUX_OPT_A10G_SUBMIT_URL,
        poll_url=config.MODAL_FLUX_OPT_A10G_POLL_URL,
        submit_url_label="MODAL_FLUX_OPT_A10G_SUBMIT_URL",
        poll_url_label="MODAL_FLUX_OPT_A10G_POLL_URL",
        payload=payload,
    )


async def invoke_flux_opt_h100(payload: dict[str, Any]) -> dict[str, Any]:
    return await _submit_and_poll(
        label="flux_opt_h100",
        submit_url=config.MODAL_FLUX_OPT_H100_SUBMIT_URL,
        poll_url=config.MODAL_FLUX_OPT_H100_POLL_URL,
        submit_url_label="MODAL_FLUX_OPT_H100_SUBMIT_URL",
        poll_url_label="MODAL_FLUX_OPT_H100_POLL_URL",
        payload=payload,
    )
