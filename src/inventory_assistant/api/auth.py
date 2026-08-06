"""Shared HTTP Basic access gate."""

from __future__ import annotations

import base64
import binascii
import secrets

from fastapi.security.utils import get_authorization_scheme_param
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

PUBLIC_HEALTH_PATHS = frozenset({"/health/live", "/health/ready"})


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Require the configured shared credential on every non-health path."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in PUBLIC_HEALTH_PATHS:
            return await call_next(request)

        if not _credentials_are_valid(request):
            return _unauthorized_response()

        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "private, no-store")
        return response


def _credentials_are_valid(request: Request) -> bool:
    authorization = request.headers.get("Authorization", "")
    scheme, encoded = get_authorization_scheme_param(authorization)
    if scheme.casefold() != "basic" or not encoded:
        return False

    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
        username, password = decoded.split(":", 1)
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False

    settings = request.app.state.settings
    username_matches = secrets.compare_digest(
        username.encode("utf-8"), settings.demo_username.encode("utf-8")
    )
    password_matches = secrets.compare_digest(
        password.encode("utf-8"), settings.demo_password.encode("utf-8")
    )
    return username_matches & password_matches


def _unauthorized_response() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": "Unauthorized"},
        headers={
            "WWW-Authenticate": "Basic",
            "Cache-Control": "no-store",
        },
    )
