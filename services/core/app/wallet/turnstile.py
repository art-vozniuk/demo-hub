"""Turnstile siteverify. Skipped when TURNSTILE_SECRET is unset (dev).
Network errors fail open so a Cloudflare hiccup doesn't block demos."""

import logging

import httpx
from fastapi import Request

from ..config import config

log = logging.getLogger(__name__)

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TURNSTILE_HEADER = "x-turnstile-token"


async def verify_turnstile(request: Request) -> bool:
    secret = config.TURNSTILE_SECRET
    if not secret:
        return True

    token = request.headers.get(TURNSTILE_HEADER)
    if not token:
        log.warning("anonymous request missing Turnstile token")
        return False

    client_ip = (
        request.headers.get("x-real-ip")
        or (request.client.host if request.client else "")
    ).strip()

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                VERIFY_URL,
                data={
                    "secret": secret,
                    "response": token,
                    "remoteip": client_ip or None,
                },
            )
            data = resp.json()
            if not data.get("success"):
                log.warning(
                    f"Turnstile rejected: {data.get('error-codes')}"
                )
                return False
            return True
    except Exception as e:
        log.error(f"Turnstile verify exception, failing open: {e}")
        return True
