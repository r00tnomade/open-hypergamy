"""Loopback HTTP server for the onboarding GUI (stdlib `http.server`, no extra dependencies).

Binds 127.0.0.1 only; there is deliberately no option to listen on another interface.
Access logs are suppressed: URLs could carry a launch code.
"""

from __future__ import annotations

import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from open_hypergamy.gui.app import MAX_BODY, GuiApp, Request
from open_hypergamy.gui.security import SessionManager
from open_hypergamy.gui.service import OnboardingService

HOST = "127.0.0.1"


class _Handler(BaseHTTPRequestHandler):
    server_version = "OpenHypergamy"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    app: GuiApp  # set on the subclass created per server
    timeout = 30  # seconds per socket read: a stalled client can't pin a thread forever

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        return

    def _serve(self) -> None:
        raw = self.headers.get("Content-Length") or "0"
        if not raw.isdigit():  # also rejects negatives, which would make read() wait for EOF
            self.send_error(400)
            return
        length = int(raw)
        if length > MAX_BODY:
            self.send_error(413)
            return
        body = self.rfile.read(length) if length else b""
        headers = {k.lower(): v for k, v in self.headers.items()}
        resp = self.app.handle(Request(self.command, self.path, headers, body))
        self.send_response(resp.status)
        for k, v in resp.headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(resp.body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(resp.body)

    do_GET = do_POST = do_PUT = do_DELETE = _serve


class GuiServer:
    def __init__(self, service: OnboardingService, port: int = 0) -> None:
        handler: type[_Handler] = type("Handler", (_Handler,), {})
        self.httpd = ThreadingHTTPServer((HOST, port), handler)
        self.httpd.daemon_threads = True
        self.port = int(self.httpd.server_address[1])
        self.sessions = SessionManager(self.port)
        handler.app = GuiApp(service, self.sessions)

    def launch_url(self, code: str | None = None) -> str:
        return f"http://{HOST}:{self.port}/launch?code={self.sessions.issue_launch_code(code)}"

    def serve_forever(self) -> None:
        self.httpd.serve_forever(poll_interval=0.5)

    def start_background(self) -> threading.Thread:
        t = threading.Thread(target=self.serve_forever, daemon=True)
        t.start()
        return t

    def shutdown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def open_browser(url: str) -> bool:
    try:
        return webbrowser.open(url, new=1)
    except webbrowser.Error:
        return False
