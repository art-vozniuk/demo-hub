"""Thin async client for the Modal-hosted FLUX inference endpoint."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from services.dispatch.app.config import config

log = logging.getLogger(__name__)


class ModalInferenceError(RuntimeError):
    pass


async def invoke_generative_editing(
    payload: dict[str, Any],
) -> dict[str, Any]:
    url = config.MODAL_GENERATIVE_ENDPOINT_URL
    if not url:
        raise ModalInferenceError(
            "MODAL_GENERATIVE_ENDPOINT_URL not configured. "
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
