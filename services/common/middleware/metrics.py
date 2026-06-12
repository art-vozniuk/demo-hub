"""HTTP RED metrics, recorded against the matched route *template* so
label cardinality stays bounded; /metrics and /health are excluded."""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_EXCLUDED_PATHS = {"/metrics", "/health"}


class HTTPMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        from services.common.observability.metrics import (
            http_request_duration_seconds,
        )

        if request.url.path in _EXCLUDED_PATHS:
            return await call_next(request)

        t0 = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            route = request.scope.get("route")
            route_path = getattr(route, "path", None) or "unmatched"
            http_request_duration_seconds.labels(
                method=request.method,
                route=route_path,
                status=f"{status_code // 100}xx",
            ).observe(time.perf_counter() - t0)
