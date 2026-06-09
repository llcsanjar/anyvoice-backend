# security/middleware.py

from fastapi import Request
from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import os

ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN")

class FrontendOnlyMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):

        origin = request.headers.get("origin")
        referer = request.headers.get("referer")

        # Allow server-to-server requests without origin
        if origin is None and referer is None:
            return await call_next(request)

        # Check Origin
        if origin and not origin.startswith(ALLOWED_ORIGIN):
            return JSONResponse(
                status_code=403,
                content={"detail": "Forbidden request origin"}
            )

        if origin and origin != ALLOWED_ORIGIN:
            return JSONResponse(
                status_code=403,
                content={"detail": "Forbidden request origin"}
            )

        # Check Referer
        if referer and not referer.startswith(ALLOWED_ORIGIN):
            return JSONResponse(
                status_code=403,
                content={"detail": "Forbidden request referer"}
            )

        response = await call_next(request)
        return response
