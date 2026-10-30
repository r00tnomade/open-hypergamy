"""Policy-aware HTTP fetcher (LLD §7.1, §7.2).

Order: canonicalize/validate -> scope -> host cooldown -> per-host slot + throttle ->
conditional request -> manual redirects (re-validated each hop) -> size/type caps ->
access-barrier check -> bounded, jittered retries (ADR-009).
Egress (ADR-012): direct by default. Sources assigned to trusted proxy profiles use them via
`egress_scope`; only proxy-infrastructure failures fail over, never destination responses, and
there is never a silent direct fallback. HostGate keys on the destination host only.
SSRF note: addresses are validated just before each request; a hostile resolver could still
rebind between validation and connect. Pinning the connection IP is a future hardening step.
"""

from __future__ import annotations

import hashlib
import logging
import random
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from open_hypergamy.clock import Clock, SystemClock
from open_hypergamy.config import AppSettings, CrawlingSettings, LoadedConfig
from open_hypergamy.egress.classify import ProxyFailure, classify_proxy_error
from open_hypergamy.egress.pool import EgressPool, Route, current_scope
from open_hypergamy.egress.security import scrub
from open_hypergamy.egress.settings import ProxyProfile
from open_hypergamy.egress.transport import EgressClients, TransportFactory
from open_hypergamy.errors import (
    AccessBarrier,
    ContentTooLarge,
    EgressUnavailable,
    FetchError,
    FetchHTTPError,
    FetchNetworkError,
    FetchTimeout,
    HostCoolingDown,
    OhgError,
    RenderingRequired,
    SourcePolicyDenied,
    UnsupportedContentType,
)
from open_hypergamy.sources.barriers import detect_barrier, detect_js_shell
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
_RESTRICTION_STATUS = {401, 403, 429, 451}  # never a reason to change egress (ADR-012)
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
_OVERLOAD_STATUS = {429, 503}
MAX_RETRY_AFTER_SECONDS = 30.0
_EWMA = 0.3
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


@dataclass
class HostStats:
    """Per-origin transport state for this process (AutoThrottle-style, ADR-009)."""

    delay: float
    slots: threading.BoundedSemaphore
    next_start: float = -1e9
    latency_ewma: float | None = None
    requests: int = 0
    statuses: dict[int, int] = field(default_factory=dict)
    cooldown_until: float = -1e9


class HostGate:
    """Per-host concurrency slots, minimum spacing and adaptive delay. Thread-safe.

    The configured minimum interval is a floor: adaptation only ever slows a host down
    (slow responses, 429/503), never below the floor.
    """

    def __init__(
        self,
        *,
        min_interval: float,
        max_delay: float,
        max_concurrency: int,
        adaptive: bool,
        monotonic: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self.min_interval, self.max_delay = min_interval, max(max_delay, min_interval)
        self.max_concurrency, self.adaptive = max_concurrency, adaptive
        self._mono, self._sleep = monotonic, sleep
        self._lock = threading.Lock()
        self._hosts: dict[str, HostStats] = {}

    def stats(self, host: str) -> HostStats:
        with self._lock:
            st = self._hosts.get(host)
            if st is None:
                st = self._hosts[host] = HostStats(
                    self.min_interval, threading.BoundedSemaphore(self.max_concurrency)
                )
            return st

    def snapshot(self) -> dict[str, HostStats]:
        with self._lock:
            return dict(self._hosts)

    @contextmanager
    def slot(self, host: str) -> Iterator[None]:
        st = self.stats(host)
        with st.slots:
            with self._lock:  # reserve a start time so concurrent callers stay spaced out
                now = self._mono()
                start = max(now, st.next_start)
                st.next_start = start + st.delay
            if start > now:
                self._sleep(start - now)
            yield

    def observe(self, host: str, latency: float, status: int | None) -> None:
        st = self.stats(host)
        with self._lock:
            st.requests += 1
            if status is not None:
                st.statuses[status] = st.statuses.get(status, 0) + 1
            st.latency_ewma = (
                latency
                if st.latency_ewma is None
                else _EWMA * latency + (1 - _EWMA) * st.latency_ewma
            )
            if not self.adaptive:
                return
            target = max(self.min_interval, (st.delay + latency) / 2)
            if status in _OVERLOAD_STATUS:
                target = max(target, st.delay * 2)
            elif status not in (200, 304):
                target = max(target, st.delay)  # errors never speed a host up
            st.delay = min(self.max_delay, target)
            # A grown delay also applies to the very next request: space it from this one's start.
            st.next_start = max(st.next_start, self._mono() - latency + st.delay)

    def cool_down(self, host: str, seconds: float) -> None:
        st = self.stats(host)
        with self._lock:
            st.cooldown_until = max(st.cooldown_until, self._mono() + seconds)

    def cooldown_remaining(self, host: str) -> float:
        st = self.stats(host)
        with self._lock:
            return max(0.0, st.cooldown_until - self._mono())


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
        jitter: Callable[[], float] = random.random,
        egress: EgressPool | None = None,
        proxy_transport_factory: TransportFactory | None = None,
    ) -> None:
        self.app = app
        self.crawling = crawling
        self.resolver = resolver
        self.clock = clock or SystemClock()
        self._mono = monotonic
        self._sleep = sleep
        self._jitter = jitter
        self.gate = HostGate(
            min_interval=app.per_host_min_interval_seconds,
            max_delay=app.max_host_delay_seconds,
            max_concurrency=app.per_host_max_concurrency,
            adaptive=app.adaptive_throttle,
            monotonic=monotonic,
            sleep=sleep,
        )
        self._robots: dict[str, RobotsInfo | None] = {}
        self._robots_lock = threading.Lock()
        self._client = httpx.Client(
            transport=transport,
            follow_redirects=False,
            headers={"User-Agent": app.effective_user_agent()},
            timeout=httpx.Timeout(10.0, read=app.request_timeout_seconds),
            trust_env=False,  # ambient HTTP(S)_PROXY/ALL_PROXY must never reroute crawler traffic
        )
        self._egress = egress
        self._egress_clients: EgressClients | None = None
        if egress is not None:
            self._egress_clients = EgressClients(
                egress.settings,
                user_agent=app.effective_user_agent(),
                timeout=httpx.Timeout(10.0, read=app.request_timeout_seconds),
                transport_factory=proxy_transport_factory,
            )
            egress.prober = self._probe_profile

    @property
    def egress(self) -> EgressPool | None:
        return self._egress

    def close(self) -> None:
        self._client.close()
        if self._egress_clients is not None:
            self._egress_clients.close()

    # -- policy helpers -------------------------------------------------------------------
    def _validate(self, url: str) -> str:
        return validate_public_url(
            url, permitted_schemes=self.crawling.permitted_schemes, resolver=self.resolver
        )

    def _backoff(self, attempt: int) -> float:
        """Exponential backoff with jitter: 2 s, 4 s, ... each scaled by [0.5, 1.5)."""
        return float(2.0 * 2**attempt * (0.5 + self._jitter()))

    def robots_info(self, url: str) -> RobotsInfo | None:
        """Informational robots.txt snapshot for the URL's origin; cached per origin.

        ADR-008: this never gates a request. Any failure (network, status, SSRF) yields None.
        """
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        with self._robots_lock:
            if origin in self._robots:
                return self._robots[origin]
        info: RobotsInfo | None = None
        try:
            status, _, body, _ = self._send_chain(
                self._validate(origin + "/robots.txt"),
                {},
                scope=None,
                route=self._route_for(host_of(origin)),
            )
            if status == 200:
                info = RobotsInfo(body.decode("utf-8", "replace").splitlines())
        except (FetchError, OhgError):
            info = None
        with self._robots_lock:
            self._robots[origin] = info
        return info

    # -- egress ---------------------------------------------------------------------------
    def _route_for(self, host: str) -> Route | None:
        """Egress route for the current source scope; None means a direct connection.

        A source that is assigned to proxies never gets None: if none is usable this raises
        EgressUnavailable (no silent direct fallback).
        """
        scope = current_scope()
        pool = self._egress
        if pool is None or scope is None:
            return None
        if scope.forced_profile is None and not pool.wants_proxy(scope.source_key):
            return None
        return pool.acquire(scope, host)

    def _client_for(self, route: Route | None) -> httpx.Client:
        if route is None or self._egress_clients is None:
            return self._client
        return self._egress_clients.client(route.profile)

    def _probe_profile(self, profile: ProxyProfile) -> bool:
        """Recovery/health probe through one profile, throttled by the same HostGate."""
        pool = self._egress
        if pool is None or self._egress_clients is None:
            return False
        url = self._validate(pool.settings.health_check_url or "")
        host = host_of(url)
        try:
            with self.gate.slot(host):
                client = self._egress_clients.client(profile.name)
                with client.stream("GET", url) as resp:
                    return 200 <= resp.status_code < 400
        except (httpx.HTTPError, OhgError):
            return False

    def _proxy_failed(self, route: Route, host: str, failure: ProxyFailure) -> None:
        """Record a proxy-infrastructure failure and fail over, or raise. Never goes direct."""
        pool = self._egress
        assert pool is not None
        profile = pool.settings.profile(route.profile)
        failed = route.profile
        pool.report_failure(route, failure)
        if failure is ProxyFailure.DENIED:
            raise SourcePolicyDenied(f"egress proxy {failed} refused this destination")
        if failure is ProxyFailure.TLS_VERIFY:
            raise FetchNetworkError(
                f"TLS verification failed via egress proxy {failed}", retryable=False
            )
        if pool.failover(route, host, failure):
            log.info("egress failover %s -> %s (%s)", failed, route.profile, failure.value)
            return
        raise EgressUnavailable(
            scrub(f"egress proxy {failed} failed ({failure.value}); no failover possible", profile)
        )

    # -- transport ------------------------------------------------------------------------
    def _send_chain(
        self,
        url: str,
        headers: dict[str, str],
        *,
        scope: Scope | None,
        accept: frozenset[str] = DEFAULT_ACCEPT,
        timing: list[float] | None = None,
        route: Route | None = None,
    ) -> tuple[int, httpx.Headers, bytes, str]:
        """One request plus redirects. Returns (status, headers, body, final_url).

        The body is only read for 200 responses, subject to type and size caps. Network time
        per hop (excluding throttle waits) is appended to `timing` and fed to the host gate.
        Each hop (and each failover attempt) takes a slot on the *destination* host's gate.
        """
        current = url
        for _ in range(self.app.max_redirects + 1):
            host = host_of(current)
            while True:
                try:
                    result = self._hop(current, host, headers, scope, accept, timing, route)
                except _ProxyHopFailure as pf:
                    assert route is not None
                    self._proxy_failed(route, host, pf.failure)
                    continue  # same hop, replacement profile
                break
            if isinstance(result, str):
                current = result
                continue
            return result
        raise FetchHTTPError(f"more than {self.app.max_redirects} redirects from {url}")

    def _hop(
        self,
        current: str,
        host: str,
        headers: dict[str, str],
        scope: Scope | None,
        accept: frozenset[str],
        timing: list[float] | None,
        route: Route | None,
    ) -> str | tuple[int, httpx.Headers, bytes, str]:
        """One request. Returns the next URL for a redirect, or the final response."""
        client = self._client_for(route)
        with self.gate.slot(host):
            t0 = self._mono()
            status: int | None = None
            proxy_fault = False
            try:
                with client.stream("GET", current, headers=headers) as resp:
                    status = resp.status_code
                    if route is not None and status == 407:
                        proxy_fault = True  # proxy authentication, never a destination answer
                        raise _ProxyHopFailure(ProxyFailure.AUTH)
                    if resp.status_code in _REDIRECTS and resp.headers.get("location"):
                        nxt = self._validate(urljoin(current, resp.headers["location"]))
                        if scope is not None:
                            scope.check_fetchable(nxt)
                        self._observe_route(route, t0)
                        return nxt
                    if resp.status_code != 200:
                        self._observe_route(route, t0)
                        return resp.status_code, resp.headers, b"", current
                    body = self._read_body(resp, accept)
                    self._observe_route(route, t0)
                    return 200, resp.headers, body, current
            except _ProxyHopFailure:
                raise
            except httpx.TransportError as e:
                failure = classify_proxy_error(e) if route is not None else None
                if failure is not None:
                    proxy_fault = True
                    raise _ProxyHopFailure(failure) from None  # message may carry the address
                if isinstance(e, httpx.TimeoutException):
                    raise FetchTimeout(f"timeout fetching {current}: {e}", retryable=True) from e
                raise FetchNetworkError(
                    f"network error fetching {current}: {e}", retryable=True
                ) from e
            finally:
                latency = self._mono() - t0
                if not proxy_fault:  # a dead proxy says nothing about the destination's pace
                    self.gate.observe(host, latency, status)
                if timing is not None:
                    timing.append(latency)

    def _observe_route(self, route: Route | None, t0: float) -> None:
        if route is not None and self._egress is not None:
            self._egress.report_success(route, self._mono() - t0)

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
        host = host_of(canonical)
        remaining = self.gate.cooldown_remaining(host)
        if remaining > 0:
            raise HostCoolingDown(
                f"{host} asked us to back off; not requesting {canonical} for {remaining:.0f}s",
                retry_after=remaining,
            )

        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        route = self._route_for(host)  # raises EgressUnavailable; never silently direct
        timing: list[float] = []
        retries = 0
        while True:
            try:
                status, h, body, final = self._send_chain(
                    canonical, headers, scope=scope, accept=accept, timing=timing, route=route
                )
                self._note_destination(route, host, status)
                if status in _RETRYABLE_STATUS:
                    ra = _retry_after(h.get("retry-after"), self.clock.now_utc())
                    raise FetchHTTPError(
                        f"HTTP {status} from {final}",
                        http_status=status,
                        retry_after=ra,
                        retryable=True,
                    )
                if status not in (200, 304):
                    raise FetchHTTPError(f"HTTP {status} from {final}", http_status=status)
                if status == 200:
                    mime = h.get("content-type", "").split(";")[0].strip().lower() or None
                    reason = detect_barrier(canonical, final, mime, body)
                    if reason:
                        self._note_destination(route, host, 200, barrier=True)
                        raise AccessBarrier(f"{reason} at {final}", http_status=200)
                    shell = detect_js_shell(mime, body)
                    if shell:
                        raise RenderingRequired(f"{shell} at {final}", http_status=200)
                break
            except FetchError as e:
                if not e.retryable or retries >= self.app.max_retries:
                    self._maybe_cool_host(host, e)
                    raise
                delay = e.retry_after if e.retry_after is not None else self._backoff(retries)
                if delay > MAX_RETRY_AFTER_SECONDS:
                    self._maybe_cool_host(host, e)
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
            elapsed_ms=int(sum(timing) * 1000),
            retry_count=retries,
            fetched_at=self.clock.now_utc(),
        )

    def _note_destination(
        self, route: Route | None, host: str, status: int, *, barrier: bool = False
    ) -> None:
        """Record the destination's answer. An access restriction pins the host to the egress
        identity that saw it; nothing here ever selects another identity (ADR-012)."""
        if route is None or self._egress is None:
            return
        route.report.destination_status = status
        if barrier or status in _RESTRICTION_STATUS:
            self._egress.note_restriction(host, route)

    def _maybe_cool_host(self, host: str, e: FetchError) -> None:
        """After an overload signal (429/503) survives retries, pause the whole host for the
        rest of this process so other sources on it are not hit in the same run."""
        if e.http_status in _OVERLOAD_STATUS:
            seconds = max(e.retry_after or 0.0, self.app.host_cooldown_seconds)
            self.gate.cool_down(host, seconds)


class _ProxyHopFailure(Exception):
    """Internal signal: this hop failed because of the proxy, not the destination."""

    def __init__(self, failure: ProxyFailure) -> None:
        super().__init__(failure.value)
        self.failure = failure


def _retry_after(value: str | None, now: datetime) -> float | None:
    """Retry-After as delta-seconds or an HTTP-date (RFC 9110 §10.2.3); None if unusable."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        return None
    return max(0.0, (when - now).total_seconds())


def build_fetcher(cfg: LoadedConfig, clock: Clock | None = None) -> Fetcher:
    proxy = cfg.settings.proxy
    pool = EgressPool(proxy, resolver=default_resolver) if proxy.enabled else None
    return Fetcher(cfg.settings.app, cfg.settings.crawling, clock=clock, egress=pool)
