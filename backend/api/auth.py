"""Minimal same-origin business login endpoints, separate from the Site gate."""

import json

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from backend.services import auth


MAX_LOGIN_BODY_BYTES = 8192


def _response(payload, token=None, *, clear=False):
    response = JSONResponse(payload, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
    if token is not None:
        response.set_cookie(auth.COOKIE_NAME, token, max_age=auth.SESSION_SECONDS if token.startswith("s.") else auth.BOOTSTRAP_SECONDS,
                            secure=True, httponly=True, samesite="strict", path="/")
    if clear:
        response.delete_cookie(auth.COOKIE_NAME, secure=True, httponly=True, samesite="strict", path="/")
    return response


def register_auth_routes(app, settings):
    @app.get("/api/admin/session")
    def session(request: Request):
        payload, token = auth.session_status(request, settings)
        return _response(payload, token)

    @app.post("/api/admin/session/login")
    async def login(request: Request):
        # Bound the stream before parsing, even without a truthful Content-Length header.
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_LOGIN_BODY_BYTES:
                auth._error(413, "maintenance_input_too_large", "登录输入超过允许大小。")
            body.extend(chunk)
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError):
            auth._error(422, "maintenance_invalid_input", "登录输入格式无效。")
        if not isinstance(payload, dict) or set(payload) != {"password"} or not isinstance(payload["password"], str) or not payload["password"] or len(payload["password"]) > auth.MAX_PASSWORD_LENGTH:
            auth._error(422, "maintenance_invalid_input", "登录输入格式无效。")
        payload, token = await run_in_threadpool(auth.login, request, settings, payload["password"])
        return _response(payload, token)

    @app.post("/api/admin/session/logout")
    def logout(request: Request):
        auth.logout(request, settings)
        return _response({"authenticated": False}, clear=True)
