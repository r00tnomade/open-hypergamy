"""Policy-aware HTTP fetcher (LLD §7.1, §7.2).

Order: canonicalize/validate -> scope -> throttle -> conditional request ->
manual redirects (re-validated each hop) -> size/type caps -> bounded retries.
SSRF note: addresses are validated just before each request; a hostile resolver could still
rebind between validation and connect. Pinning the connection IP is a future hardening step.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from open_hypergamy.clock import Clock, SystemClock
from open_hypergamy.config import AppSettings, CrawlingSettings, LoadedConfig
from open_hypergamy.errors import (
    ContentTooLarge,
    FetchError,
    FetchHTTPError,
    FetchNetworkError,
    FetchTimeout,
    OhgError,
    UnsupportedContentType,
)
from open_hypergamy.sources.policy import RobotsInfo, Scope
from open_hypergamy.sources.urls import Resolver, default_resolver, host_of, validate_public_url

log = logging.getLogger(__name__)

DEFAULT_ACCEPT = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
        "text/plain",
        "text/xml",
        "application/xml",
        "application/rss+xml",
        "application/atom+xml",
        "application/rdf+xml",
        "text/calendar",
    }
)
_REDIRECTS = {301, 302, 303, 307, 308}
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
MAX_RETRY_AFTER_SECONDS = 30.0
_CHUNK = 64 * 1024


@dataclass(frozen=True)
class FetchResponse:
    requested_url: str
    final_url: str
    status: int
    mime_type: str | None
    etag: str | None
    last_modified: str | None
    body: bytes
    not_modified: bool
    elapsed_ms: int
    retry_count: int
    fetched_at: datetime


class BodyCache:
    """Content-hash addressed files under <home>/cache (LLD §1.2)."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def store(self, data: bytes, suffix: str) -> tuple[str, str]:
        digest = hashlib.sha256(data).hexdigest()
        rel = f"bodies/{digest[:2]}/{digest}.{suffix}"
        path = self.root / rel
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        return rel, digest


class Fetcher:
    def __init__(
        self,
        app: AppSettings,
        crawling: CrawlingSettings,
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: Resolver = default_resolver,
        clock: Clock | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.app = app
        self.crawling = crawling
        self.resolver = resolver
        self.clock = clock or SystemClock()
        self._mono = monotonic
        self._sleep = sleep
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, RobotsInfo | None] = {}
        self._client = httpx.Client(
            transport=transport,
            follow_redirects=False,
            headers={"User-Agent": app.user_agent},
            timeout=httpx.Timeout(10.0, read=app.request_timeout_seconds),
        )

    def close(self) -> None:
        self._client.close()

    # -- policy helpers -------------------------------------------------------------------
    def _validate(self, url: str) -> str:
        return validate_public_url(
            url, permitted_schemes=self.crawling.permitted_schemes, resolver=self.resolver
        )

    def _throttle(self, host: str) -> None:
        wait = self.app.per_host_min_interval_seconds - (
            self._mono() - self._last_hit.get(host, -1e9)
        )
        if wait > 0:
            self._sleep(wait)
        self._last_hit[host] = self._mono()

    def robots_info(self, url: str) -> RobotsInfo | None:
        """Informational robots.txt snapshot for the URL's origin; cached per origin.

        ADR-008: this never gates a request. Any failure (network, status, SSRF) yields None.
        """
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            info: RobotsInfo | None = None
            try:
                status, _, body, _ = self._send_chain(
                    self._validate(origin + "/robots.txt"), {}, scope=None
                )
                if status == 200:
                    info = RobotsInfo(body.decode("utf-8", "replace").splitlines())
            except (FetchError, OhgError):
                info = None
            self._robots[origin] = info
        return self._robots[origin]

    # -- transport ------------------------------------------------------------------------
    def _send_chain(
        self,
        url: str,
        headers: dict[str, str],
        *,
        scope: Scope | None,
        accept: frozenset[str] = DEFAULT_ACCEPT,
    ) -> tuple[int, httpx.Headers, bytes, str]:
        """One request plus redirects. Returns (status, headers, body, final_url).

        The body is only read for 200 responses, subject to type and size caps.
        """
        current = url
        for _ in range(self.app.max_redirects + 1):
            self._throttle(host_of(current))
            try:
                with self._client.stream("GET", current, headers=headers) as resp:
                    if resp.status_code in _REDIRECTS and resp.headers.get("location"):
                        nxt = self._validate(urljoin(current, resp.headers["location"]))
                        if scope is not None:
                            scope.check_fetchable(nxt)
                        current = nxt
                        continue
                    if resp.status_code != 200:
                        return resp.status_code, resp.headers, b"", current
                    return 200, resp.headers, self._read_body(resp, accept), current
            except httpx.TimeoutException as e:
                raise FetchTimeout(f"timeout fetching {current}: {e}", retryable=True) from e
            except httpx.TransportError as e:
                raise FetchNetworkError(
                    f"network error fetching {current}: {e}", retryable=True
                ) from e
        raise FetchHTTPError(f"more than {self.app.max_redirects} redirects from {url}")

    def _read_body(self, resp: httpx.Response, accept: frozenset[str]) -> bytes:
        mime = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        if mime and mime not in accept:
            raise UnsupportedContentType(f"unsupported content type: {mime}")
        limit = self.app.max_response_bytes
        declared = resp.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            raise ContentTooLarge(f"Content-Length {declared} exceeds {limit} bytes")
        buf = bytearray()
        for chunk in resp.iter_bytes(_CHUNK):  # decoded bytes: also bounds compression bombs
            buf += chunk
            if len(buf) > limit:
                raise ContentTooLarge(f"response body exceeds {limit} bytes")
        return bytes(buf)

    # -- public API -----------------------------------------------------------------------
    def fetch(
        self,
        url: str,
        scope: Scope,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        accept: frozenset[str] = DEFAULT_ACCEPT,
    ) -> FetchResponse:
        canonical = self._validate(url)
        scope.check_fetchable(canonical)

        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        started = self._mono()
        retries = 0
        while True:
            try:
                status, h, body, final = self._send_chain(
                    canonical, headers, scope=scope, accept=accept
                )
                if status in _RETRYABLE_STATUS:
                    ra = _retry_after(h.get("retry-after"))
                    raise FetchHTTPError(
                        f"HTTP {status} from {final}",
                        http_status=status,
                        retry_after=ra,
                        retryable=True,
                    )
                if status not in (200, 304):
                    raise FetchHTTPError(f"HTTP {status} from {final}", http_status=status)
                break
            except FetchError as e:
                if not e.retryable or retries >= self.app.max_retries:
                    raise
                delay = e.retry_after if e.retry_after is not None else 2.0 * 2**retries
                if delay > MAX_RETRY_AFTER_SECONDS:
                    raise  # server asked us to back off longer than we are willing to wait
                log.info("retrying %s in %.1fs (%s)", canonical, delay, e)
                self._sleep(delay)
                retries += 1
        return FetchResponse(
            requested_url=canonical,
            final_url=final,
            status=status,
            mime_type=h.get("content-type", "").split(";")[0].strip().lower() or None,
            etag=h.get("etag"),
            last_modified=h.get("last-modified"),
            body=body,
            not_modified=status == 304,
            elapsed_ms=int((self._mono() - started) * 1000),
            retry_count=retries,
            fetched_at=self.clock.now_utc(),
        )


def _retry_after(value: str | None) -> float | None:
    if value and value.strip().isdigit():
        return float(value.strip())
    return None


def build_fetcher(cfg: LoadedConfig, clock: Clock | None = None) -> Fetcher:
    return Fetcher(cfg.settings.app, cfg.settings.crawling, clock=clock)
