"""Supabase Storage helpers for editor-scene asset cleanup."""

from __future__ import annotations

import logging
from typing import Iterable
from urllib.parse import urlparse

import httpx

from ..config import config

log = logging.getLogger(__name__)

# Bucket assets live in. Same as the web side ASSET_BUCKET.
_BUCKET = "media"
# Marker between bucket and key in public URLs:
# https://<proj>.supabase.co/storage/v1/object/public/<bucket>/<key>
_PUBLIC_MARKER = f"/storage/v1/object/public/{_BUCKET}/"


def url_to_key(url: str) -> str | None:
    """Extract the storage key from a public Supabase URL. None if the URL
    doesn't point at our bucket."""
    p = urlparse(url)
    path = p.path
    if _PUBLIC_MARKER in path:
        return path.split(_PUBLIC_MARKER, 1)[1]
    return None


async def delete_keys(keys: Iterable[str]) -> None:
    """Best-effort delete. Failures are logged but never raised — orphan
    objects are tolerable; a failed save is not."""
    if not config.SUPABASE_SERVICE_ROLE_KEY:
        log.warning("editor_scenes.storage: no service role key, skipping deletes")
        return
    keys = [k for k in keys if k]
    if not keys:
        return
    url = f"{config.SUPABASE_URL}/storage/v1/object/{_BUCKET}"
    headers = {
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
        "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=10.0) as cx:
        try:
            r = await cx.request(
                "DELETE", url, headers=headers, json={"prefixes": list(keys)}
            )
            if r.status_code >= 400:
                log.warning(
                    "editor_scenes.storage: delete failed %s %s", r.status_code, r.text
                )
        except Exception as e:
            log.warning("editor_scenes.storage: delete exception %s", e)


async def list_keys_under_prefix(prefix: str) -> list[str]:
    """Recursively list every key with the given prefix in our bucket."""
    if not config.SUPABASE_SERVICE_ROLE_KEY:
        return []
    out: list[str] = []
    cursor = 0
    page = 200
    url = f"{config.SUPABASE_URL}/storage/v1/object/list/{_BUCKET}"
    headers = {
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
        "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=10.0) as cx:
        while True:
            try:
                r = await cx.post(
                    url,
                    headers=headers,
                    json={"prefix": prefix, "limit": page, "offset": cursor},
                )
                if r.status_code >= 400:
                    log.warning(
                        "editor_scenes.storage: list failed %s %s",
                        r.status_code,
                        r.text,
                    )
                    break
                rows = r.json() or []
                if not isinstance(rows, list) or not rows:
                    break
                for row in rows:
                    name = row.get("name")
                    if not name:
                        continue
                    # Supabase list returns entries relative to the prefix;
                    # rejoin to get the full key.
                    full = f"{prefix}/{name}" if prefix else name
                    out.append(full)
                if len(rows) < page:
                    break
                cursor += page
            except Exception as e:
                log.warning("editor_scenes.storage: list exception %s", e)
                break
    return out


def manifest_asset_urls(manifest: dict) -> set[str]:
    """Pull every `asset.url` out of a manifest dict."""
    urls: set[str] = set()
    for o in (manifest or {}).get("objects") or []:
        a = o.get("asset") if isinstance(o, dict) else None
        if isinstance(a, dict):
            u = a.get("url")
            if isinstance(u, str) and u:
                urls.add(u)
    return urls
