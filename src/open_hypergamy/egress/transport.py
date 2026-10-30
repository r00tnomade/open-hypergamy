"""One isolated httpx client per proxy profile (ADR-012).

Isolation properties: `trust_env=False` (ambient proxy variables are never read), separate
cookie jars/connection pools per profile (no session sharing across egress identities), TLS
verification always on, and the proxy CA never trusted for destinations.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

import httpx

from open_hypergamy.egress.security import proxy_ssl_context, resolve_credentials
from open_hypergamy.egress.settings import ProxyProfile, ProxySettings

TransportFactory = Callable[[ProxyProfile], httpx.BaseTransport]


class EgressClients:
    def __init__(
        self,
        settings: ProxySettings,
        *,
        user_agent: str,
        timeout: httpx.Timeout,
        transport_factory: TransportFactory | None = None,
    ) -> None:
        self._settings = settings
        self._ua = user_agent
        self._timeout = timeout
        self._factory = transport_factory  # tests inject a fake "proxy"; production leaves None
        self._lock = threading.Lock()
        self._clients: dict[str, httpx.Client] = {}

    def client(self, name: str) -> httpx.Client:
        with self._lock:
            existing = self._clients.get(name)
            if existing is not None:
                return existing
            client = self._build(self._settings.profile(name))
            self._clients[name] = client
            return client

    def _build(self, profile: ProxyProfile) -> httpx.Client:
        common = {
            "follow_redirects": False,
            "headers": {"User-Agent": self._ua},
            "timeout": self._timeout,
            "trust_env": False,
        }
        if self._factory is not None:
            return httpx.Client(transport=self._factory(profile), **common)  # type: ignore[arg-type]
        creds = resolve_credentials(profile)
        proxy = httpx.Proxy(
            profile.url,
            auth=creds,
            ssl_context=proxy_ssl_context(profile) if profile.scheme == "https" else None,
        )
        # `verify=True` (default CA store) governs the destination's certificate; the proxy's
        # optional CA bundle lives only in the Proxy object above.
        return httpx.Client(proxy=proxy, verify=True, **common)  # type: ignore[arg-type]

    def close(self) -> None:
        with self._lock:
            for c in self._clients.values():
                c.close()
            self._clients.clear()
