"""Cross-app submit/poll for the single web gateway: route payload["model"]
to a per-model app's class by name (each model keeps its own deploy)."""

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
    model = payload.get("model")
    route = routes.get(model) if isinstance(model, str) else None
    # pipeline_id (injected by dispatch) doubles as the request id so
    # gateway logs grep together with dispatch + container logs.
    request_id = str(payload.get("pipeline_id") or uuid.uuid4().hex[:8])
    if route is None:
        log.warning(f"[{request_id}] gateway: unknown model {model!r}")
        return {"error": f"unknown model: {model!r}"}

    app_name, class_name = route
    try:
        cls = modal.Cls.from_name(app_name, class_name)
        # payload carries the Sentry trace headers through to the model
        # app untouched — the container resumes the pipeline's trace.
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
