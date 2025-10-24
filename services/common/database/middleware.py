import logging
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from .core import async_session_maker

log = logging.getLogger(__name__)


class DatabaseMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        async with async_session_maker() as session:
            request.state.db = session
            try:
                response = await call_next(request)

                if response.status_code < 400:
                    await session.commit()
                else:
                    await session.rollback()

                return response
            except Exception as e:
                await session.rollback()
                log.error(f"database error: {e}")
                raise
            finally:
                await session.close()
