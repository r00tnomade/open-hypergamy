"""Proxy pool: health, selection, affinity, failover (ADR-012). Thread-safe, no network I/O.

The pool decides *which trusted profile* carries a request. It never looks at destination
statuses except through `note_restriction`, which only ever *pins* a host (no rotation).
"""

from __future__ import annotations

import contextlib
import contextvars
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum

from open_hypergamy.egress.classify import ProxyFailure
from open_hypergamy.egress.security import EndpointRejected, Resolver, check_endpoint_addresses
from open_hypergamy.egress.settings import ProxyProfile, ProxySettings
from open_hypergamy.errors import EgressUnavailable

_EWMA = 0.3
Prober = Callable[[ProxyProfile], bool]


class ProxyHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"  # failed recently, still in rotation
    UNHEALTHY = "unhealthy"  # cooling down; out of rotation
    DISABLED = "disabled"


@dataclass
class ProxyState:
    health: ProxyHealth = ProxyHealth.HEALTHY
    consecutive_failures: int = 0
    total_failures: int = 0
    total_successes: int = 0
    cooldown_until: float = -1e9
    cooldown_step: int = 0
    latency_ewma_ms: float | None = None
    last_failure: ProxyFailure | None = None
    failures_by_kind: dict[str, int] = field(default_factory=dict)


@dataclass
class EgressReport:
    """What happened to one source check's traffic. Names only; no addresses or credentials."""

    profile: str | None = None  # last profile used
    profiles_used: list[str] = field(default_factory=list)
    rotation_count: int = 0
    failover_count: int = 0
    proxy_failures: dict[str, int] = field(default_factory=dict)
    proxy_latency_ms: int | None = None
    destination_status: int | None = None
    health: dict[str, str] = field(default_factory=dict)

    @property
    def used(self) -> bool:
        return bool(self.profiles_used) or bool(self.proxy_failures)

    def as_json(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "profiles_used": self.profiles_used,
            "rotation_count": self.rotation_count,
            "failover_count": self.failover_count,
            "proxy_failures": dict(sorted(self.proxy_failures.items())),
            "proxy_latency_ms": self.proxy_latency_ms,
            "destination_status": self.destination_status,
            "proxy_health": dict(sorted(self.health.items())),
        }


@dataclass
class Route:
    """The egress identity for one fetch call. Mutated in place by failover."""

    profile: str
    source_key: str | None
    candidates: list[str]
    report: EgressReport
    forced: bool = False  # operator-selected: no rotation, no failover
    failovers: int = 0
    tried: set[str] = field(default_factory=set)


@dataclass
class EgressScope:
    source_key: str | None
    report: EgressReport
    forced_profile: str | None = None


_scope: contextvars.ContextVar[EgressScope | None] = contextvars.ContextVar(
    "ohg_egress_scope", default=None
)


@contextlib.contextmanager
def egress_scope(
    source_key: str | None, report: EgressReport | None = None, *, forced_profile: str | None = None
) -> Iterator[EgressReport]:
    """Bind the current thread's fetches to a source (and optionally a manual profile)."""
    rep = report if report is not None else EgressReport()
    token = _scope.set(EgressScope(source_key, rep, forced_profile))
    try:
        yield rep
    finally:
        _scope.reset(token)


def current_scope() -> EgressScope | None:
    return _scope.get()


class EgressPool:
    def __init__(
        self,
        settings: ProxySettings,
        *,
        resolver: Resolver,
        prober: Prober | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self._resolver = resolver
        self.prober = prober
        self._mono = monotonic
        self._lock = threading.Lock()
        self._states = {
            p.name: ProxyState(ProxyHealth.HEALTHY if p.enabled else ProxyHealth.DISABLED)
            for p in settings.profiles
        }
        self._rr: dict[tuple[str, ...], int] = {}
        self._sticky: dict[str, str] = {}
        self._last_selected: dict[str, str] = {}
        self._restricted: dict[str, str] = {}  # destination host -> profile pinned after a block

    # -- inspection -------------------------------------------------------------------------
    def state(self, name: str) -> ProxyState:
        return self._states[name]

    def snapshot(self) -> dict[str, ProxyState]:
        with self._lock:
            return dict(self._states)

    def health_of(self, name: str) -> ProxyHealth:
        return self._states[name].health

    # -- acquisition ------------------------------------------------------------------------
    def wants_proxy(self, source_key: str | None) -> bool:
        return self.settings.is_assigned(source_key)

    def acquire(self, scope: EgressScope, host: str) -> Route:
        """Pick a profile for a source's request. Raises EgressUnavailable rather than ever
        returning 'direct' for a source that is meant to use a proxy."""
        source = scope.source_key
        if scope.forced_profile is not None:
            name = scope.forced_profile
            self._require_known(name)
            self._ensure_usable(name)
            self._record_use(scope.report, name)
            return Route(name, source, [name], scope.report, forced=True, tried={name})
        candidates = self.settings.candidates_for(source)
        if not candidates:
            raise EgressUnavailable(f"all egress profiles for {source or 'this request'} are off")
        pinned = self._restricted.get(host)
        if pinned is not None:
            if pinned not in candidates:
                raise EgressUnavailable(f"egress for {host} is pinned after an access restriction")
            candidates = [pinned]
        name = self._select(source, candidates, scope.report, pinned=pinned is not None)
        return Route(name, source, candidates, scope.report, tried={name})

    def _select(
        self, source: str | None, candidates: list[str], report: EgressReport, *, pinned: bool
    ) -> str:
        sticky = self._sticky.get(source or "") if self.settings.affinity == "source" else None
        checked: str | None = None
        if sticky in candidates and not pinned:
            checked = sticky
            if self._usable(sticky):
                self._remember(source, sticky, report, pinned=pinned)  # never advances RR
                return sticky
        for name in self._order(candidates):
            if name != checked and self._usable(name):
                self._remember(source, name, report, pinned=pinned)
                return name
        raise EgressUnavailable("no healthy egress profile is available")

    def _order(self, candidates: list[str]) -> list[str]:
        if self.settings.selection == "least_failure":
            return sorted(
                candidates,
                key=lambda n: (
                    self._states[n].consecutive_failures,
                    self._states[n].total_failures,
                    self._states[n].latency_ewma_ms or 0.0,
                    n,
                ),
            )
        key = tuple(candidates)
        with self._lock:
            start = self._rr.get(key, 0) % len(candidates)
            self._rr[key] = start + 1
        return candidates[start:] + candidates[:start]

    def _remember(
        self, source: str | None, name: str, report: EgressReport, *, pinned: bool
    ) -> None:
        with self._lock:
            if source is not None:
                previous = self._last_selected.get(source)
                if previous is not None and previous != name and not pinned:
                    report.rotation_count += 1
                self._last_selected[source] = name
                if self.settings.affinity == "source":
                    self._sticky[source] = name
        self._record_use(report, name)

    def _record_use(self, report: EgressReport, name: str) -> None:
        report.profile = name
        if name not in report.profiles_used:
            report.profiles_used.append(name)

    def _require_known(self, name: str) -> None:
        if name not in self._states:
            raise EgressUnavailable("unknown egress profile")

    def _ensure_usable(self, name: str) -> None:
        if not self._usable(name):
            raise EgressUnavailable("the selected egress profile is not available")

    # -- health -----------------------------------------------------------------------------
    def _usable(self, name: str) -> bool:
        """In rotation? Unhealthy profiles come back only after cooldown AND a passing probe."""
        profile = self.settings.profile(name)
        st = self._states[name]
        if not profile.enabled or st.health is ProxyHealth.DISABLED:
            return False
        if st.health is ProxyHealth.UNHEALTHY:
            if self._mono() < st.cooldown_until:
                return False
            if not self._recover(profile):
                return False
        try:
            check_endpoint_addresses(profile, self._resolver)
        except EndpointRejected:
            self.report_failure_state(name, ProxyFailure.ENDPOINT_REJECTED)
            return False
        except Exception:  # resolver failure: the proxy name does not resolve right now
            self.report_failure_state(name, ProxyFailure.DNS)
            return False
        return True

    def _recover(self, profile: ProxyProfile) -> bool:
        """Probe an unhealthy proxy before reintroducing it (never with a real source request)."""
        st = self._states[profile.name]
        ok = False
        if self.prober is not None:
            try:
                ok = self.prober(profile)
            except Exception:  # noqa: BLE001 - a broken prober must not take sources down
                ok = False
        with self._lock:
            if ok:
                st.health = ProxyHealth.DEGRADED
                st.consecutive_failures = 0
                st.cooldown_step = 0
                st.cooldown_until = -1e9
            else:
                self._start_cooldown(st)
        return ok

    def _start_cooldown(self, st: ProxyState) -> None:
        s = self.settings
        seconds = min(s.cooldown_seconds * 2**st.cooldown_step, s.max_cooldown_seconds)
        st.cooldown_step += 1
        st.cooldown_until = self._mono() + seconds
        st.health = ProxyHealth.UNHEALTHY

    def report_success(self, route: Route, latency_s: float) -> None:
        ms = latency_s * 1000
        with self._lock:
            st = self._states[route.profile]
            st.total_successes += 1
            st.consecutive_failures = 0
            if st.health is ProxyHealth.DEGRADED:
                st.health = ProxyHealth.HEALTHY
            st.latency_ewma_ms = (
                ms if st.latency_ewma_ms is None else _EWMA * ms + (1 - _EWMA) * st.latency_ewma_ms
            )
            route.report.proxy_latency_ms = int(st.latency_ewma_ms)
            route.report.health[route.profile] = str(st.health)

    def report_failure_state(self, name: str, failure: ProxyFailure) -> None:
        with self._lock:
            st = self._states[name]
            st.total_failures += 1
            st.consecutive_failures += 1
            st.last_failure = failure
            st.failures_by_kind[failure.value] = st.failures_by_kind.get(failure.value, 0) + 1
            if failure is ProxyFailure.DENIED:
                return  # the proxy answered; its ACL said no. Not an outage.
            if failure is ProxyFailure.ENDPOINT_REJECTED or (
                st.consecutive_failures >= self.settings.failure_threshold
            ):
                self._start_cooldown(st)
            elif st.health is ProxyHealth.HEALTHY:
                st.health = ProxyHealth.DEGRADED

    def report_failure(self, route: Route, failure: ProxyFailure) -> None:
        self.report_failure_state(route.profile, failure)
        rep = route.report
        rep.proxy_failures[failure.value] = rep.proxy_failures.get(failure.value, 0) + 1
        rep.health[route.profile] = str(self._states[route.profile].health)

    # -- failover ---------------------------------------------------------------------------
    def failover(self, route: Route, host: str, failure: ProxyFailure) -> bool:
        """Replace the route's profile after a proxy-infrastructure failure. Bounded; never
        direct; refused for operator-forced routes and for hosts that restricted access."""
        if route.forced or not failure.failover_allowed or host in self._restricted:
            return False
        if route.failovers >= self.settings.max_failovers:
            return False
        for name in self._order(route.candidates):
            if name in route.tried or not self._usable(name):
                continue
            route.failovers += 1
            route.tried.add(name)
            route.profile = name
            route.report.failover_count += 1
            with self._lock:
                if route.source_key is not None:
                    self._last_selected[route.source_key] = name
                    if self.settings.affinity == "source":
                        self._sticky[route.source_key] = name
            self._record_use(route.report, name)
            return True
        return False

    def note_restriction(self, host: str, route: Route) -> None:
        """A destination restricted access (401/403/429/451/challenge). Keep this host on the
        identity that saw it; do not rotate and do not fail over for it (no circumvention)."""
        with self._lock:
            self._restricted.setdefault(host, route.profile)

    def release_restrictions(self) -> None:
        """Forget host pins. Only an operator decision (a new process does the same)."""
        with self._lock:
            self._restricted.clear()

    def restricted_hosts(self) -> dict[str, str]:
        with self._lock:
            return dict(self._restricted)
