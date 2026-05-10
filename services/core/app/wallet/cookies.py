"""Signed httpOnly cookie carrying the anonymous wallet UUID. Format:
`<uuid>.<base64url(hmac_sha256(secret, uuid))>`. Clearing the cookie
yields a new wallet by design — Turnstile + IP rate-limit handle bots."""

import base64
import hashlib
import hmac
from typing import Optional
from uuid import UUID, uuid4

from fastapi import Request, Response

from ..config import config

ANON_COOKIE_NAME = "anon_id"
COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365  # 1 year


def _sign(value: str, secret: str) -> str:
    sig = hmac.new(secret.encode(), value.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")


def _wrap(value: str, secret: str) -> str:
    return f"{value}.{_sign(value, secret)}"


def _unwrap(signed: str, secret: str) -> Optional[str]:
    if "." not in signed:
        return None
    value, sig = signed.rsplit(".", 1)
    expected = _sign(value, secret)
    if not hmac.compare_digest(sig, expected):
        return None
    return value


def read_anon_id(request: Request) -> Optional[UUID]:
    raw = request.cookies.get(ANON_COOKIE_NAME)
    if not raw:
        return None
    secret = config.WALLET_COOKIE_SECRET
    if not secret:
        return None
    value = _unwrap(raw, secret)
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def issue_anon_id(response: Response) -> UUID:
    secret = config.WALLET_COOKIE_SECRET
    if not secret:
        raise RuntimeError("WALLET_COOKIE_SECRET is not configured")
    new_id = uuid4()
    response.set_cookie(
        ANON_COOKIE_NAME,
        _wrap(str(new_id), secret),
        max_age=COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        # Secure=False in dev so localhost http can keep the cookie.
        secure=(config.ENV != "development"),
        samesite="lax",
        path="/",
    )
    return new_id
