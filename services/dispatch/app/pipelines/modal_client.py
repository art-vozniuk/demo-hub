"""Thin async clients for Modal-hosted inference endpoints.

One callable per deployed Modal app (FLUX generative editing, SHARP).
FLUX uses a plain sync POST; SHARP can outrun Modal's ~60s gateway cap
on a cold start, so it goes through a submit + poll loop instead.
Shared header + timeout logic lives in `_post_to_modal`.
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


async def invoke_generative_editing(
    payload: dict[str, Any],
) -> dict[str, Any]:
    return await _post_to_modal(
        "MODAL_GENERATIVE_ENDPOINT_URL",
        config.MODAL_GENERATIVE_ENDPOINT_URL,
        payload,
    )


async def invoke_sharp(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Submit + poll. Modal's sync endpoint gateway drops connections at ~60s."""

    submit_resp = await _post_to_modal(
        "MODAL_SHARP_SUBMIT_URL",
        config.MODAL_SHARP_SUBMIT_URL,
        payload,
    )
    if "error" in submit_resp:
        raise ModalInferenceError(f"Modal submit failed: {submit_resp['error']}")
    call_id = submit_resp.get("call_id")
    request_id = submit_resp.get("request_id")
    if not call_id:
        raise ModalInferenceError(
            f"Modal submit returned no call_id; body={submit_resp}"
        )

    log.info(f"[{request_id}] sharp submit ok; polling call_id={call_id}")
    deadline = time.monotonic() + config.MODAL_REQUEST_TIMEOUT_SECONDS
    poll_count = 0
    while True:
        if time.monotonic() > deadline:
            raise ModalInferenceError(
                f"Modal poll timed out after "
                f"{config.MODAL_REQUEST_TIMEOUT_SECONDS}s; call_id={call_id}"
            )

        poll_resp = await _post_to_modal(
            "MODAL_SHARP_POLL_URL",
            config.MODAL_SHARP_POLL_URL,
            {"call_id": call_id},
        )
        poll_count += 1
        status = poll_resp.get("status")
        if status == "done":
            log.info(
                f"[{request_id}] sharp done after {poll_count} polls; "
                f"call_id={call_id}"
            )
            return poll_resp["result"]
        if status in ("failed", "expired", "error"):
            raise ModalInferenceError(
                f"Modal poll status={status}; call_id={call_id} "
                f"error={poll_resp.get('error')}"
            )
        await asyncio.sleep(config.MODAL_POLL_INTERVAL_SECONDS)
