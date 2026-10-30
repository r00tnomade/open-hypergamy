"""Doubles for egress-proxy tests: a scriptable fake proxy and a fetcher wired to a pool."""

from __future__ import annotations

import ssl
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from open_hypergamy.config import AppSettings, CrawlingSettings
from open_hypergamy.egress.pool import EgressPool
from open_hypergamy.egress.settings import ProxyProfile, ProxySettings
from open_hypergamy.sources.fetch import Fetcher
from tests.helpers import PUBLIC_IP, FakeWeb, html, public_dns

HEALTH_URL = "https://health.example.org/ok"
Behavior = Callable[[httpx.Request], httpx.Response]


def cert_error() -> httpx.ConnectError:
    err = httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
    err.__cause__ = ssl.SSLCertVerificationError(1, "certificate verify failed")
    return err


class FakeProxy(httpx.BaseTransport):
    """Stands in for one proxy endpoint. `mode` is a response, an exception or a callable;
    `None` forwards to the destination web (an honest proxy)."""

    def __init__(self, name: str, web: FakeWeb) -> None:
        self.name, self.web = name, web
        self.mode: httpx.Response | Exception | Behavior | None = None
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        mode = self.mode
        if isinstance(mode, Exception):
            raise mode
        if isinstance(mode, httpx.Response):
            return mode
        if callable(mode):
            return mode(request)
        return self.web._handle(request)

    @property
    def urls(self) -> list[str]:
        return [str(r.url) for r in self.requests]


def profile(name: str, **kw: object) -> ProxyProfile:
    data: dict[str, object] = {
        "name": name,
        "url": f"https://{name}.proxy.example.net:8443",
        "trusted": True,
    }
    data.update(kw)
    return ProxyProfile(**data)  # type: ignore[arg-type]


def settings(names: tuple[str, ...] = ("p1", "p2"), **kw: object) -> ProxySettings:
    data: dict[str, object] = {
        "enabled": True,
        "trusted_endpoint_hosts": [f"{n}.proxy.example.net" for n in names],
        "health_check_url": HEALTH_URL,
        "profiles": [profile(n) for n in names],
        "default_profiles": list(names),
    }
    data.update(kw)
    return ProxySettings(**data)  # type: ignore[arg-type]


@dataclass
class Rig:
    fetcher: Fetcher
    pool: EgressPool
    proxies: dict[str, FakeProxy]
    direct: FakeWeb  # what a *direct* connection would reach: must stay untouched
    web: FakeWeb  # the destinations, reachable through the proxies
    sleeps: list[float]
    now: list[float] = field(default_factory=lambda: [0.0])

    def advance(self, seconds: float) -> None:
        self.now[0] += seconds


def rig(
    routes: dict[str, httpx.Response | Callable[[httpx.Request], httpx.Response]] | None = None,
    *,
    proxy_settings: ProxySettings | None = None,
    app: AppSettings | None = None,
    resolver: Callable[[str], list[str]] = public_dns,
    pool_resolver: Callable[[str], list[str]] = public_dns,
) -> Rig:
    s = proxy_settings or settings()
    web = FakeWeb({HEALTH_URL: html(b"ok"), **(routes or {})})
    direct = FakeWeb(dict(routes or {}))  # same pages: a direct request would succeed
    proxies = {p.name: FakeProxy(p.name, web) for p in s.profiles}
    sleeps: list[float] = []
    now = [0.0]

    def sleep(sec: float) -> None:
        sleeps.append(sec)
        now[0] += sec

    pool = EgressPool(s, resolver=pool_resolver, monotonic=lambda: now[0])
    fetcher = Fetcher(
        app or AppSettings(),
        CrawlingSettings(),
        transport=direct.transport,
        resolver=resolver,
        monotonic=lambda: now[0],
        sleep=sleep,
        jitter=lambda: 0.5,
        egress=pool,
        proxy_transport_factory=lambda p: proxies[p.name],
    )
    return Rig(fetcher, pool, proxies, direct, web, sleeps, now)


__all__ = ["PUBLIC_IP", "FakeProxy", "Rig", "cert_error", "profile", "rig", "settings"]
