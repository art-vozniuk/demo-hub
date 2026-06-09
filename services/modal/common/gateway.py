"""Cross-app submit/poll used by the single web gateway.

Only the gateway app exposes web endpoints (Modal's free tier caps them
per workspace); it routes spawn calls to the per-model apps by name, so
each model keeps its own deploy with an isolated image + memory snapshot.
The spawn/poll mechanics live here once instead of being copied per app.
"""

from __future__ import annotations

import uuid
from typing import Any, Mapping

import modal

from .lib import poll_function_call


def submit(
    routes: Mapping[str, tuple[str, str]],
    payload: Mapping[str, Any],
    log,
) -> dict[str, Any]:
    """Route payload["model"] -> (app_name, class_name) and spawn that
    class's `generate` with the raw payload. Returns a call_id to poll."""

    model = payload.get("model")
    route = routes.get(model) if isinstance(model, str) else None
    request_id = uuid.uuid4().hex[:8]
    if route is None:
        log.warning(f"[{request_id}] gateway: unknown model {model!r}")
        return {"error": f"unknown model: {model!r}"}

    app_name, class_name = route
    try:
        cls = modal.Cls.from_name(app_name, class_name)
        call = cls().generate.spawn(dict(payload))
    except Exception as e:
        log.error(f"[{request_id}] gateway spawn failed ({model}): {e}")
        return {"error": f"spawn failed: {e}"}

    log.info(
        f"[{request_id}] gateway submit model={model} "
        f"-> {app_name}.{class_name} call_id={call.object_id}"
    )
    return {"call_id": call.object_id, "request_id": request_id}


def poll(payload: Mapping[str, Any], log) -> dict[str, Any]:
    """Resolve a spawned call. Model-agnostic — call_id is global."""
    return poll_function_call(payload.get("call_id"), log)
