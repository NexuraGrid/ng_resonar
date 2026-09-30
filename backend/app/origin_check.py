"""Reject cross-origin writes that ride on the session cookie.

The session cookie is ``SameSite=Lax``. That stops cross-*site* POSTs, but the
sibling apps under the same registrable domain (``*.nexuragrid.com``) are
*same-site*, so a script on any of them could still send a credentialed
``fetch(..., {mode: "no-cors"})`` POST with no Content-Type — which FastAPI
parses as JSON. Browsers always attach ``Origin`` to such a request, so any
unsafe ``/api/`` request whose ``Origin`` is not this host (or an explicitly
allowed CORS origin) is refused.

Requests without ``Origin`` (curl, server-to-server) are let through: they
cannot carry a victim's browser cookie.
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

_UNSAFE = {b"POST", b"PUT", b"PATCH", b"DELETE"}


class OriginCheckMiddleware:
    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed = {o.rstrip("/").lower() for o in allowed_origins}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"].encode() not in _UNSAFE
            or not scope["path"].startswith("/api/")
        ):
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        origin = headers.get(b"origin", b"").decode("latin-1").strip().lower()
        if not origin or self._same_host(origin, headers) or origin in self.allowed:
            await self.app(scope, receive, send)
            return

        body = json.dumps({"detail": "Cross-origin request blocked"}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    def _same_host(origin: str, headers: dict[bytes, bytes]) -> bool:
        if origin == "null":
            return False
        origin_host = urlsplit(origin).netloc
        host = headers.get(b"host", b"").decode("latin-1").strip().lower()
        return bool(origin_host) and origin_host == host
