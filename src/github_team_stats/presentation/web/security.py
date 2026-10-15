"""Local browser session and request-origin protection."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


@dataclass(slots=True)
class LocalSession:
    origin: str
    bootstrap_token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    session_token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    bootstrap_used: bool = False

    def valid_session(self, candidate: str | None) -> bool:
        return candidate is not None and secrets.compare_digest(candidate, self.session_token)


class LocalSecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, session: LocalSession) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._session = session

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.hostname != "127.0.0.1":
            return JSONResponse({"detail": "Localhost access only"}, status_code=403)

        bootstrap = request.query_params.get("session")
        if request.url.path == "/" and bootstrap and not self._session.bootstrap_used:
            if secrets.compare_digest(bootstrap, self._session.bootstrap_token):
                self._session.bootstrap_used = True
                response = RedirectResponse("/", status_code=303)
                response.set_cookie(
                    "gma_session",
                    self._session.session_token,
                    httponly=True,
                    samesite="strict",
                    secure=False,
                )
                return self._secure(response)

        if not self._session.valid_session(request.cookies.get("gma_session")):
            return JSONResponse({"detail": "Invalid or expired UI session"}, status_code=401)

        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("origin") != self._session.origin:
                return JSONResponse({"detail": "Invalid request origin"}, status_code=403)

        return self._secure(await call_next(request))

    @staticmethod
    def _secure(response: Response) -> Response:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; script-src 'self'; "
            "style-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        )
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if response.headers.get("content-type", "").startswith("application/json"):
            response.headers["Cache-Control"] = "no-store"
        return response
