"""Single web gateway — the only Modal app that exposes web endpoints.

Modal's free tier caps web functions per workspace, so instead of a
submit/poll pair per model (2 x N) we keep ONE pair here and route to the
per-model apps by name (modal.Cls.from_name). Each model app exposes no
web function of its own — just its GPU class + preload, invoked here.
Adding a model = one ROUTES entry, zero new web functions.
"""

from __future__ import annotations

from typing import Any

import modal

from common.lib import configure_logging
from common.gateway import submit as gw_submit, poll as gw_poll


log = configure_logging("gateway")
app = modal.App("demo-hub-gateway")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("fastapi[standard]==0.115.6", "pydantic==2.10.3")
    .add_local_python_source("common.lib", "common.gateway")
)


# payload["model"] (sent by dispatch) -> (app_name, class_name). The class
# must expose a `generate` method accepting the raw payload dict.
ROUTES: dict[str, tuple[str, str]] = {
    "flux_opt_a10g": ("demo-hub-flux-opt", "FluxOptA10G"),
    "flux_opt_h100": ("demo-hub-flux-opt", "FluxOptH100"),
    # To migrate a live model: drop its own web endpoints, make generate()
    # take the raw payload dict, then enable its route here.
    # "generative_editing": ("demo-hub-flux-opt", "FluxOptA10G"),
    # "sharp":              ("demo-hub-sharp", "SharpInference"),
    # "trellis":            ("demo-hub-trellis", "TrellisInference"),
    # "generative_t2i":     ("demo-hub-flux-t2i", "FluxT2IInference"),
}


@app.function(image=image, timeout=120)
@modal.fastapi_endpoint(method="POST", requires_proxy_auth=True)
def submit(payload: dict[str, Any]) -> dict[str, Any]:
    return gw_submit(ROUTES, payload, log)


@app.function(image=image, timeout=120)
@modal.fastapi_endpoint(method="POST", requires_proxy_auth=True)
def poll(payload: dict[str, Any]) -> dict[str, Any]:
    return gw_poll(payload, log)
