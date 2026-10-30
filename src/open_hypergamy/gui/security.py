"""Request authentication for the loopback onboarding server (ADR-014).

- The browser is opened at `/launch?code=…` with a one-time, short-lived code. Redeeming it sets
  an HttpOnly, SameSite=Strict session cookie and redirects to `/`, so the URL in history is
  dead. Codes are single-use; a second redeem fails.
- Every API request needs the session cookie. State-changing requests also need the CSRF token
  (handed to the page by `GET /api/session`) in `X-OHG-CSRF`, a matching `Origin`, and a JSON
  body. Host must be the exact loopback authority (DNS-rebinding defence).
- Tokens are compared in constant time and never logged.
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

COOKIE = "ohg_session"
CSRF_HEADER = "x-ohg-csrf"
LAUNCH_TTL_SECONDS = 300
SESSION_TTL_SECONDS = 12 * 3600

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}


@dataclass
class _Session:
    token: str
    csrf: str
    expires: float


@dataclass
class SessionManager:
    port: int
    now: Callable[[], float] = time.monotonic
    _codes: dict[str, float] = field(default_factory=dict)
    _sessions: dict[str, _Session] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def authorities(self) -> set[str]:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    @property
    def origins(self) -> set[str]:
        return {f"http://{a}" for a in self.authorities}

    def issue_launch_code(self, code: str | None = None) -> str:
        code = code or secrets.token_urlsafe(32)
        with self._lock:
            self._codes[code] = self.now() + LAUNCH_TTL_SECONDS
        return code

    def redeem(self, code: str) -> _Session | None:
        with self._lock:
            match = next((c for c in self._codes if hmac.compare_digest(c, code)), None)
            if match is None:
                return None
            expires = self._codes.pop(match)  # single use, even when expired
            if expires < self.now():
                return None
            s = _Session(
                secrets.token_urlsafe(32),
                secrets.token_urlsafe(32),
                self.now() + SESSION_TTL_SECONDS,
            )
            self._sessions[s.token] = s
            return s

    def session(self, cookie_value: str | None) -> _Session | None:
        if not cookie_value:
            return None
        with self._lock:
            for tok, s in list(self._sessions.items()):
                if s.expires < self.now():
                    del self._sessions[tok]
            return next(
                (s for t, s in self._sessions.items() if hmac.compare_digest(t, cookie_value)),
                None,
            )

    def csrf_ok(self, s: _Session, header: str | None) -> bool:
        return bool(header) and hmac.compare_digest(s.csrf, header or "")

    def host_ok(self, host: str | None) -> bool:
        return (host or "").lower() in self.authorities

    def origin_ok(self, origin: str | None) -> bool:
        return (origin or "").lower() in self.origins

    def cookie_header(self, s: _Session) -> str:
        # No `Secure`: the server is plain http on loopback by design; SameSite=Strict + HttpOnly.
        return (
            f"{COOKIE}={s.token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL_SECONDS}"
        )


def parse_cookie(header: str | None, name: str = COOKIE) -> str | None:
    for part in (header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return v
    return None
