"""Bound request bodies before parsing and apply a shared database-backed API budget."""

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse

from app.auth_dependencies import DB, throttle
from app.config import get_settings


def api_budget(request: Request, db: DB):
    if request.url.path not in {"/api/v1/health", "/api/v1/ready"}:
        throttle(db, request, "api.requests", ip_limit=600)


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        settings = get_settings()
        path = scope.get("path", "")
        maximum = (
            settings.audio_max_bytes if path.endswith("/audio-analyses") else
            settings.visual_max_bytes if path.endswith("/visual-analyses") else 32768
        )
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
            if declared < 0:
                raise ValueError
        except ValueError:
            return await JSONResponse({"detail": "Invalid request length"}, 400)(scope, receive, send)
        if declared > maximum:
            return await JSONResponse({"detail": "Request too large"}, 413)(scope, receive, send)
        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > maximum:
                    raise HTTPException(413, "Request too large")
            return message

        await self.app(scope, bounded_receive, send)
