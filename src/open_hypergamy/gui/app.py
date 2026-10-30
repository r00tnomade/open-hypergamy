"""Transport-independent request handling for the onboarding GUI.

`GuiApp.handle(Request) -> Response` does routing, authentication, CSRF/Host/Origin checks and
JSON encoding. `server.py` adapts it to `http.server`; tests call it directly.
"""

from __future__ import annotations

import json
import logging
import mimetypes
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import resources
from typing import Any
from urllib.parse import parse_qs, urlsplit

from open_hypergamy.gui.security import (
    CSRF_HEADER,
    SECURITY_HEADERS,
    SessionManager,
    parse_cookie,
)
from open_hypergamy.gui.service import ApiError, OnboardingService
from open_hypergamy.observability.logging import redact

log = logging.getLogger(__name__)
MAX_BODY = 64_000


@dataclass
class Request:
    method: str
    path: str  # may include a query string
    headers: dict[str, str]  # lower-case names
    body: bytes = b""


@dataclass
class Response:
    status: int
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)


def _json(status: int, data: Any, extra: dict[str, str] | None = None) -> Response:
    return Response(
        status,
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode(),
        {
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "no-store",
            **(extra or {}),
        },
    )


def _error(status: int, message: str, fields: dict[str, str] | None = None) -> Response:
    return _json(status, {"error": message, "fields": fields or {}})


_EXPIRED_PAGE = b"""<!doctype html><html lang="en"><meta charset="utf-8"><title>OpenHypergamy</title>
<link rel="stylesheet" href="/static/expired.css"><main><h1>This setup link has expired</h1>
<p>For your safety each link works once. Run <code>ohg onboard</code> again to open a fresh session.</p></main></html>"""

Handler = Callable[[OnboardingService, Any], dict[str, Any]]


def _routes() -> dict[tuple[str, str], Handler]:
    return {
        ("GET", "/api/state"): lambda s, _: s.snapshot(),
        ("PUT", "/api/draft"): lambda s, b: s.save_draft(
            str((b or {}).get("step")), (b or {}).get("data")
        ),
        ("POST", "/api/step"): lambda s, b: s.mark_step(
            str((b or {}).get("step")), str((b or {}).get("status")), (b or {}).get("current")
        ),
        ("POST", "/api/profile"): lambda s, b: s.save_profile(b),
        ("POST", "/api/preferences"): lambda s, b: s.save_preferences(b),
        ("POST", "/api/preview"): lambda s, _: s.preview(),
        ("POST", "/api/telegram/token"): lambda s, b: s.telegram_token(b),
        ("POST", "/api/telegram/chat/detect"): lambda s, _: s.telegram_detect_chat(),
        ("POST", "/api/telegram/chat"): lambda s, b: s.telegram_pick_chat(b),
        ("POST", "/api/telegram/test"): lambda s, _: s.telegram_test(),
        ("POST", "/api/telegram/settings"): lambda s, b: s.telegram_settings(b),
        ("POST", "/api/telegram/forget"): lambda s, _: s.telegram_forget(),
        ("POST", "/api/llm/status"): lambda s, _: s.llm_status(),
        ("POST", "/api/llm/ack"): lambda s, b: s.llm_ack(b),
        ("POST", "/api/llm/key"): lambda s, b: s.llm_key(b),
        ("POST", "/api/llm/test"): lambda s, _: s.llm_test(),
        ("POST", "/api/llm/settings"): lambda s, b: s.llm_settings(b),
        ("POST", "/api/finish"): lambda s, _: s.finish(),
        ("GET", "/api/summary"): lambda s, _: s.summary(),
        ("POST", "/api/recover/settings"): lambda s, _: s.recover_settings(),
    }


class GuiApp:
    def __init__(self, service: OnboardingService, sessions: SessionManager) -> None:
        self.service, self.sessions = service, sessions
        self.routes = _routes()
        self._static = resources.files("open_hypergamy.gui") / "static"

    def handle(self, req: Request) -> Response:
        try:
            resp = self._dispatch(req)
        except Exception as e:  # noqa: BLE001 - e.g. a NUL byte in a static path; never a traceback
            log.error("gui request failed: %s", redact(type(e).__name__))
            resp = _error(
                500, "Something went wrong on our side. Your saved answers are safe; try again."
            )
        resp.headers = {**SECURITY_HEADERS, **resp.headers}
        return resp

    def _dispatch(self, req: Request) -> Response:
        if not self.sessions.host_ok(req.headers.get("host")):
            return _error(421, "Unexpected Host header.")
        url = urlsplit(req.path)
        path = url.path
        if req.method == "GET" and path == "/launch":
            code = (parse_qs(url.query).get("code") or [""])[0]
            s = self.sessions.redeem(code) if code else None
            if s is None:
                return Response(
                    403,
                    _EXPIRED_PAGE,
                    {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
                )
            return Response(
                303,
                b"",
                {
                    "Location": "/",
                    "Set-Cookie": self.sessions.cookie_header(s),
                    "Cache-Control": "no-store",
                },
            )
        if req.method == "GET" and path in ("/favicon.svg", "/favicon.ico"):
            return self._asset("brand" + path)  # browsers ask for these unprompted
        if req.method == "GET" and path.startswith("/static/"):
            return self._asset(path.removeprefix("/static/"))

        session = self.sessions.session(parse_cookie(req.headers.get("cookie")))
        if not path.startswith("/api/"):
            if req.method != "GET":
                return _error(405, "Method not allowed.")
            if session is None:
                return Response(
                    403,
                    _EXPIRED_PAGE,
                    {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
                )
            return self._asset("index.html", cache=False)  # SPA routes all serve the shell

        if session is None:
            return _error(401, "Your setup session has expired. Run `ohg onboard` again.")
        if path == "/api/session" and req.method == "GET":
            return _json(200, {"csrf": session.csrf})
        if req.method != "GET":
            if not self.sessions.origin_ok(req.headers.get("origin")):
                return _error(403, "Request origin not allowed.")
            if not self.sessions.csrf_ok(session, req.headers.get(CSRF_HEADER)):
                return _error(403, "Missing or invalid CSRF token. Reload the page.")
            if not req.headers.get("content-type", "").startswith("application/json"):
                return _error(415, "Expected application/json.")
        route = self.routes.get((req.method, path))
        if route is None:
            return _error(404, "Not found.")
        if len(req.body) > MAX_BODY:
            return _error(413, "Request too large.")
        try:
            body = json.loads(req.body) if req.body else None
        except ValueError:
            return _error(400, "Body is not valid JSON.")
        try:
            return _json(200, route(self.service, body))
        except ApiError as e:
            return _error(e.status, e.message, e.fields)
        except Exception as e:  # noqa: BLE001 - never leak a traceback or a path to the browser
            log.error(
                "gui request %s %s failed: %s", req.method, path, redact(f"{type(e).__name__}: {e}")
            )
            return _error(
                500, "Something went wrong on our side. Your saved answers are safe; try again."
            )

    def _asset(self, rel: str, *, cache: bool = True) -> Response:
        if not rel or ".." in rel.split("/") or rel.startswith("/") or "\\" in rel:
            return _error(404, "Not found.")
        f = self._static.joinpath(*rel.split("/"))
        if not f.is_file():
            if rel == "index.html":
                return Response(
                    500,
                    b"GUI assets are missing from this installation.",
                    {"Content-Type": "text/plain"},
                )
            return _error(404, "Not found.")
        ctype = mimetypes.guess_type(rel)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        hashed = rel.startswith("assets/")
        return Response(
            200,
            f.read_bytes(),
            {
                "Content-Type": ctype,
                "Cache-Control": "public, max-age=31536000, immutable"
                if hashed and cache
                else "no-cache",
            },
        )
