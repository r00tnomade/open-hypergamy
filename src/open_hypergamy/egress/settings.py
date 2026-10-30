"""Proxy configuration models (ADR-012). Validation here is static: no DNS, no secrets.

Everything is opt-in. A profile is usable only when the operator set `trusted: true` AND listed
its host in `trusted_endpoint_hosts`; credentials are referenced by secret *name* only.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, model_validator

PROXY_SCHEMES = ("http", "https", "socks5")
_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_SECRET_NAME = re.compile(r"^OHG_PROXY_[A-Z0-9_]{1,48}$")
_LOCAL_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home.arpa")
_DEFAULT_PORTS = {"http": 80, "https": 443, "socks5": 1080}


class _Strict(BaseModel):
    # Unlike the other sections, typos here must fail: a silently ignored key in a security
    # section is worse than an error. Input values are never echoed (see config.load_config).
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def address_is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global


class ProxyProfile(_Strict):
    name: str
    url: str  # scheme://host:port only; credentials are never part of the URL
    enabled: bool = True
    trusted: bool = False
    username_secret: str | None = None  # name of an env var / Keychain item, never the value
    password_secret: str | None = None
    ca_bundle: str | None = None  # extra CA for the *proxy's* TLS only (never for destinations)
    allow_private_endpoint: bool = False  # loopback/private proxy, controlled local deployment
    allow_plaintext: bool = False  # http/socks5 to a non-local proxy (e.g. inside a VPN)
    # Public addresses publishers see our requests come from. Documentation for allowlist
    # requests only (ohg sources permission-request); never used to route or to trust anything.
    egress_ips: list[str] = []

    @property
    def scheme(self) -> str:
        return urlsplit(self.url).scheme

    @property
    def host(self) -> str:
        return (urlsplit(self.url).hostname or "").lower()

    @property
    def port(self) -> int:
        return urlsplit(self.url).port or _DEFAULT_PORTS[self.scheme]

    @model_validator(mode="after")
    def _static_checks(self) -> ProxyProfile:
        if not _NAME.match(self.name):
            raise ValueError("proxy profile names are lowercase [a-z0-9_-], max 32 chars")
        parts = urlsplit(self.url)
        if parts.scheme not in PROXY_SCHEMES:
            raise ValueError(f"proxy {self.name}: scheme must be one of {list(PROXY_SCHEMES)}")
        if parts.username or parts.password or "@" in parts.netloc:
            raise ValueError(
                f"proxy {self.name}: credentials must not be part of the URL; "
                "use username_secret/password_secret"
            )
        if parts.path not in ("", "/") or parts.query or parts.fragment:
            raise ValueError(f"proxy {self.name}: url must be scheme://host:port only")
        try:
            port = parts.port
        except ValueError:
            raise ValueError(f"proxy {self.name}: invalid port") from None
        if not parts.hostname or port is None:
            raise ValueError(f"proxy {self.name}: url needs an explicit host and port")
        for secret in (self.username_secret, self.password_secret):
            if secret is not None and not _SECRET_NAME.match(secret):
                raise ValueError(
                    f"proxy {self.name}: secret names must look like OHG_PROXY_<NAME>_USER"
                )
        for ip in self.egress_ips:
            addr = literal_ip(ip)
            if addr is None or not address_is_public(str(addr)):
                raise ValueError(f"proxy {self.name}: egress_ips must be public IP addresses")
        if (self.username_secret is None) != (self.password_secret is None):
            raise ValueError(f"proxy {self.name}: set both username_secret and password_secret")
        if self.enabled:
            self._enabled_checks()
        return self

    def _enabled_checks(self) -> None:
        host = self.host
        ip = literal_ip(host)
        local = (
            (ip is not None and not address_is_public(str(ip)))
            or host == "localhost"
            or host.endswith(_LOCAL_SUFFIXES)
            or ("." not in host and ip is None)
        )
        if not self.trusted:
            raise ValueError(f"proxy {self.name}: not trusted; set trusted: true explicitly")
        if local and not self.allow_private_endpoint:
            raise ValueError(
                f"proxy {self.name}: loopback/private/link-local endpoints need "
                "allow_private_endpoint: true"
            )
        if not local and self.scheme != "https" and not self.allow_plaintext:
            raise ValueError(
                f"proxy {self.name}: {self.scheme} to a non-local endpoint is unencrypted; "
                "use https or set allow_plaintext: true (only inside a protected tunnel)"
            )


class ProxySettings(_Strict):
    enabled: bool = False
    selection: Literal["round_robin", "least_failure"] = "round_robin"
    # `source`: a source sticks to one profile until it fails; `none`: rotate per request.
    affinity: Literal["none", "source"] = "source"
    trusted_endpoint_hosts: list[str] = []
    health_check_url: str | None = None  # public https URL the operator trusts for probes
    failure_threshold: int = 2
    cooldown_seconds: float = 120.0
    max_cooldown_seconds: float = 1800.0
    max_failovers: int = 2
    profiles: list[ProxyProfile] = []
    default_profiles: list[str] = []  # used by sources without an explicit assignment
    assignments: dict[str, list[str]] = {}  # source_key -> profile names

    @model_validator(mode="after")
    def _consistency(self) -> ProxySettings:
        names = [p.name for p in self.profiles]
        if len(set(names)) != len(names):
            raise ValueError("proxy profile names must be unique")
        known = set(names)
        refs = [*self.default_profiles, *(n for v in self.assignments.values() for n in v)]
        unknown = sorted({n for n in refs if n not in known})
        if unknown:
            raise ValueError(f"unknown proxy profile(s) referenced: {unknown}")
        if not 0 <= self.max_failovers <= 5:
            raise ValueError("proxy.max_failovers must be between 0 and 5")
        if self.failure_threshold < 1 or self.cooldown_seconds <= 0:
            raise ValueError("proxy.failure_threshold >= 1 and cooldown_seconds > 0 required")
        if self.max_cooldown_seconds < self.cooldown_seconds:
            raise ValueError("proxy.max_cooldown_seconds must be >= cooldown_seconds")
        if self.enabled:
            self._enabled_checks()
        return self

    def _enabled_checks(self) -> None:
        trusted = {h.lower() for h in self.trusted_endpoint_hosts}
        active = [p for p in self.profiles if p.enabled]
        for p in active:
            if p.host not in trusted:
                raise ValueError(f"proxy {p.name}: host is not in proxy.trusted_endpoint_hosts")
        if active:
            parts = urlsplit(self.health_check_url or "")
            if parts.scheme != "https" or not parts.hostname:
                raise ValueError("proxy.health_check_url must be an https URL when proxies are on")
            ip = literal_ip(parts.hostname)
            if ip is not None and not address_is_public(str(ip)):
                raise ValueError("proxy.health_check_url must not target a non-public address")

    def profile(self, name: str) -> ProxyProfile:
        for p in self.profiles:
            if p.name == name:
                return p
        raise KeyError(name)

    def candidates_for(self, source_key: str | None) -> list[str]:
        """Profile names a source may use; empty means direct. Disabled profiles are dropped."""
        if not self.enabled or source_key is None:
            return []
        chosen = self.assignments.get(source_key, self.default_profiles)
        enabled = {p.name for p in self.profiles if p.enabled}
        return [n for n in chosen if n in enabled]

    def is_assigned(self, source_key: str | None) -> bool:
        """True when the source is meant to use a proxy (even if every profile is disabled)."""
        if not self.enabled or source_key is None:
            return False
        return bool(self.assignments.get(source_key, self.default_profiles))
