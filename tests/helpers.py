"""Shared test doubles: fake DNS, scripted HTTP transport, fixture loader."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx

from open_hypergamy.config import AppSettings, CrawlingSettings
from open_hypergamy.sources.fetch import Fetcher

FIXTURES = Path(__file__).parent / "fixtures"
PUBLIC_IP = "93.184.216.34"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def public_dns(host: str) -> list[str]:
    return [PUBLIC_IP]


class FakeWeb:
    """httpx transport recording every request; routes map URL -> response or callable."""

    def __init__(
        self, routes: dict[str, httpx.Response | Callable[[httpx.Request], httpx.Response]]
    ):
        self.routes = routes
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        route = self.routes.get(url)
        if route is None and url.endswith("/robots.txt"):
            return httpx.Response(404)
        if route is None:
            return httpx.Response(404, text="not found")
        return route(request) if callable(route) else route

    @property
    def urls(self) -> list[str]:
        return [str(r.url) for r in self.requests]


def html(body: bytes, **headers: str) -> httpx.Response:
    return httpx.Response(
        200, content=body, headers={"content-type": "text/html; charset=utf-8", **headers}
    )


def make_fetcher(
    web: FakeWeb,
    *,
    app: AppSettings | None = None,
    crawling: CrawlingSettings | None = None,
    resolver: Callable[[str], list[str]] = public_dns,
) -> tuple[Fetcher, list[float]]:
    sleeps: list[float] = []
    now = [0.0]

    def sleep(s: float) -> None:
        sleeps.append(s)
        now[0] += s

    f = Fetcher(
        app or AppSettings(), crawling or CrawlingSettings(), transport=web.transport,
        resolver=resolver, monotonic=lambda: now[0], sleep=sleep,
        jitter=lambda: 0.5,  # backoff factor exactly 1.0: 2 s, 4 s, ...
    )  # fmt: skip
    return f, sleeps
