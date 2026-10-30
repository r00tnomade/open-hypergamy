"""Tell proxy-infrastructure failures from destination behaviour (ADR-012).

Only a failure that proves the *proxy* could not carry the request may trigger failover. Any
HTTP response from the destination (403, 429, 401, 451, a challenge page, ...) is never a proxy
failure and never changes egress identity.
"""

from __future__ import annotations

import re
import socket
import ssl
from enum import StrEnum

import httpx


class ProxyFailure(StrEnum):
    CONNECT_REFUSED = "connect_refused"
    TIMEOUT = "timeout"
    DNS = "dns"
    AUTH = "auth"
    UNAVAILABLE = "unavailable"  # CONNECT/SOCKS reply 502/503/504, general failure, resets
    PROTOCOL = "protocol"  # malformed proxy reply
    ENDPOINT_REJECTED = "endpoint_rejected"  # DNS rebinding / non-public proxy address
    DENIED = "denied"  # the proxy's own ACL refused the destination: policy, not an outage
    TLS_VERIFY = "tls_verification_failed"  # could be the proxy or the destination: fail closed

    @property
    def failover_allowed(self) -> bool:
        return self not in (ProxyFailure.DENIED, ProxyFailure.TLS_VERIFY)


_STATUS = re.compile(r"^\s*(\d{3})\b")
_RULESET = re.compile(r"not allowed by ruleset|not allowed", re.I)
_AUTH = re.compile(r"auth|username|password|credential", re.I)


def _chain(exc: BaseException) -> list[BaseException]:
    seen: list[BaseException] = []
    cur: BaseException | None = exc
    while cur is not None and cur not in seen and len(seen) < 8:
        seen.append(cur)
        cur = cur.__cause__ or cur.__context__
    return seen


def classify_proxy_error(exc: BaseException) -> ProxyFailure | None:
    """Failure kind for an exception raised while using a proxied client, or None when the
    exception is not evidence about the proxy (read timeouts, protocol errors mid-response...)."""
    chain = _chain(exc)
    if any(isinstance(e, ssl.SSLCertVerificationError) for e in chain):
        return ProxyFailure.TLS_VERIFY
    if isinstance(exc, httpx.ProxyError):
        return classify_proxy_reply(str(exc))
    if isinstance(exc, httpx.ConnectTimeout):
        return ProxyFailure.TIMEOUT
    if isinstance(exc, httpx.ConnectError):
        if any(isinstance(e, socket.gaierror) for e in chain):
            return ProxyFailure.DNS
        if any(isinstance(e, ConnectionRefusedError) for e in chain):
            return ProxyFailure.CONNECT_REFUSED
        if any(isinstance(e, ssl.SSLError) for e in chain):
            return ProxyFailure.UNAVAILABLE
        return ProxyFailure.UNAVAILABLE
    return None


def classify_proxy_reply(message: str) -> ProxyFailure:
    """Map a CONNECT status line / SOCKS error text to a failure kind."""
    m = _STATUS.match(message)
    if m:
        status = int(m.group(1))
        if status == 407:
            return ProxyFailure.AUTH
        if status in (502, 503, 504):
            return ProxyFailure.UNAVAILABLE
        return ProxyFailure.DENIED  # 400/403/429/...: the proxy refused this destination
    if _RULESET.search(message):
        return ProxyFailure.DENIED
    if _AUTH.search(message):
        return ProxyFailure.AUTH
    return ProxyFailure.UNAVAILABLE
