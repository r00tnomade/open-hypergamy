"""Local simulated acquisition environment (ADR-013). No network: every "publisher" is a
deterministic in-process policy engine; every "proxy" is a transport that tells the publisher
which egress identity it carries. Nothing here models, probes or defeats a real third party.

Publisher behaviours: IP blocking, publisher-approved allowlists, HTTP rate limiting, CAPTCHA /
challenge pages, geo restriction, JavaScript-only (shell) pages, and downtime.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from open_hypergamy.config import AppSettings, CrawlingSettings
from open_hypergamy.egress.pool import EgressPool
from open_hypergamy.egress.settings import ProxyProfile, ProxySettings
from open_hypergamy.sources.fetch import Fetcher
from tests.helpers import public_dns

HEALTH_URL = "https://health.example.org/ok"
CHALLENGE = b"<html><head><title>Just a moment...</title></head><body>cf_chl_opt</body></html>"
SHELL = (
    b'<!doctype html><html><head><title>Opportunities</title><script src="/app.js"></script>'
    b'</head><body><div id="root"></div><noscript>Please enable JavaScript to view this '
    b"site.</noscript></body></html>"
)


@dataclass(frozen=True)
class Identity:
    name: str
    ip: str
    region: str


@dataclass
class Publisher:
    """One destination host's policy. `pages` maps URL -> bytes or callable(request)."""

    pages: dict[str, bytes]
    now: Callable[[], float]
    content_type: dict[str, str] = field(default_factory=dict)
    blocked_ips: set[str] = field(default_factory=set)
    allowlist_ips: set[str] | None = None  # publisher-approved egress addresses
    geo_allowed: set[str] | None = None  # None = everywhere; blocked => 451
    captcha_urls: set[str] = field(default_factory=set)
    shell_urls: set[str] = field(default_factory=set)
    rate_limit: tuple[int, float] | None = None  # (requests, per seconds), whole host
    retry_after: int = 60
    offline: bool = False
    log: list[tuple[str, str, int]] = field(default_factory=list)  # (url, identity ip, status)
    times: list[float] = field(default_factory=list)  # virtual time of each logged request
    _window: list[float] = field(default_factory=list)

    def handle(self, request: httpx.Request, who: Identity) -> httpx.Response:
        url = str(request.url)
        resp = self._decide(url, who)
        self.log.append((url, who.ip, resp.status_code))
        self.times.append(self.now())
        return resp

    def _decide(self, url: str, who: Identity) -> httpx.Response:
        if url == HEALTH_URL:
            return httpx.Response(200, text="ok", headers={"content-type": "text/plain"})
        if self.offline:
            return httpx.Response(503)
        if who.ip in self.blocked_ips or (
            self.allowlist_ips is not None and who.ip not in self.allowlist_ips
        ):
            return httpx.Response(403, text="forbidden")
        if self.geo_allowed is not None and who.region not in self.geo_allowed:
            return httpx.Response(451, text="unavailable for legal reasons")
        if self.rate_limit is not None:
            n, per = self.rate_limit
            t = self.now()
            self._window = [x for x in self._window if t - x < per]
            if len(self._window) >= n:
                return httpx.Response(429, headers={"retry-after": str(self.retry_after)})
            self._window.append(t)
        if url in self.captcha_urls:
            return httpx.Response(200, content=CHALLENGE, headers={"content-type": "text/html"})
        if url in self.shell_urls:
            return httpx.Response(200, content=SHELL, headers={"content-type": "text/html"})
        body = self.pages.get(url)
        if body is None:
            return httpx.Response(404)
        ctype = self.content_type.get(url, "text/html; charset=utf-8")
        return httpx.Response(200, content=body, headers={"content-type": ctype})

    def identities_seen(self, *, exclude_health: bool = True) -> set[str]:
        return {ip for url, ip, _ in self.log if not (exclude_health and url == HEALTH_URL)}


class SimProxy(httpx.BaseTransport):
    """A proxy endpoint: carries requests to the publisher as `identity`, or is broken."""

    def __init__(self, identity: Identity, publisher: Publisher) -> None:
        self.identity, self.publisher = identity, publisher
        self.broken: Exception | None = None
        self.requests = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        if self.broken is not None:
            raise self.broken
        return self.publisher.handle(request, self.identity)


DIRECT = Identity("direct", "198.51.100.77", "DE")
P1 = Identity("p1", "203.0.113.1", "DE")
P2 = Identity("p2", "203.0.113.2", "US")


def profile(name: str) -> ProxyProfile:
    return ProxyProfile(name=name, url=f"https://{name}.proxy.example.net:8443", trusted=True)


def proxy_settings(assign: dict[str, list[str]], **kw: object) -> ProxySettings:
    names = ["p1", "p2"]
    data: dict[str, object] = {
        "enabled": True,
        "trusted_endpoint_hosts": [f"{n}.proxy.example.net" for n in names],
        "health_check_url": HEALTH_URL,
        "profiles": [profile(n) for n in names],
        "assignments": assign,
        "failure_threshold": 1,
        "cooldown_seconds": 60.0,
        "max_cooldown_seconds": 600.0,
    }
    data.update(kw)
    return ProxySettings(**data)  # type: ignore[arg-type]


@dataclass
class Network:
    fetcher: Fetcher
    pool: EgressPool
    publisher: Publisher
    proxies: dict[str, SimProxy]
    direct: SimProxy
    now: list[float]

    def advance(self, seconds: float) -> None:
        self.now[0] += seconds


def network(
    pages: dict[str, bytes], assign: dict[str, list[str]], **publisher_kw: object
) -> Network:
    now = [0.0]
    pub = Publisher(pages=pages, now=lambda: now[0], **publisher_kw)  # type: ignore[arg-type]
    identities = {"p1": P1, "p2": P2}
    proxies = {n: SimProxy(i, pub) for n, i in identities.items()}
    direct = SimProxy(DIRECT, pub)
    s = proxy_settings(assign)
    pool = EgressPool(s, resolver=public_dns, monotonic=lambda: now[0])
    fetcher = Fetcher(
        AppSettings(),
        CrawlingSettings(),
        transport=direct,
        resolver=public_dns,
        monotonic=lambda: now[0],
        sleep=lambda sec: now.__setitem__(0, now[0] + sec),
        jitter=lambda: 0.5,
        egress=pool,
        proxy_transport_factory=lambda p: proxies[p.name],
    )
    return Network(fetcher, pool, pub, proxies, direct, now)
