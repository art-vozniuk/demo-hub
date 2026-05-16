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
import time
from typing import Any

import httpx

from services.dispatch.app.config import config

log = logging.getLogger(__name__)


class ModalInferenceError(RuntimeError):
    pass


async def _post_to_modal(
    endpoint_label: str,
    url: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not url:
        raise ModalInferenceError(
            f"{endpoint_label} not configured. "
            "See services/modal/README.md for deployment steps."
        )

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if config.MODAL_PROXY_AUTH_TOKEN_ID and config.MODAL_PROXY_AUTH_TOKEN_SECRET:
        headers["Modal-Key"] = config.MODAL_PROXY_AUTH_TOKEN_ID
        headers["Modal-Secret"] = config.MODAL_PROXY_AUTH_TOKEN_SECRET

    timeout = httpx.Timeout(config.MODAL_REQUEST_TIMEOUT_SECONDS, connect=10.0)

    log.info(f"Calling Modal endpoint: {url}")
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise ModalInferenceError(
                f"Modal returned {resp.status_code}: {resp.text[:500]}"
            )
        try:
            return resp.json()
        except ValueError as e:
            raise ModalInferenceError(f"Modal returned non-JSON body: {e}")


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
    deadline = time.monotonic() + config.MODAL_REQUEST_TIMEOUT_SECONDS
    poll_count = 0
    while True:
        if time.monotonic() > deadline:
            raise ModalInferenceError(
                f"Modal {label} poll timed out after "
                f"{config.MODAL_REQUEST_TIMEOUT_SECONDS}s; call_id={call_id}"
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


async def invoke_sharp(payload: dict[str, Any]) -> dict[str, Any]:
    return await _submit_and_poll(
        label="sharp",
        submit_url=config.MODAL_SHARP_SUBMIT_URL,
        poll_url=config.MODAL_SHARP_POLL_URL,
        submit_url_label="MODAL_SHARP_SUBMIT_URL",
        poll_url_label="MODAL_SHARP_POLL_URL",
        payload=payload,
    )
