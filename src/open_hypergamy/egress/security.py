"""Proxy endpoint, TLS and credential handling (ADR-012).

Credentials exist only as transient values read from the environment/Keychain when a client is
built. They are passed to httpx as structured auth (never embedded in a URL), and every message
that mentions a proxy goes through `scrub`.
"""

from __future__ import annotations

import re
import ssl
from collections.abc import Callable
from pathlib import Path

from open_hypergamy import keychain
from open_hypergamy.egress.settings import ProxyProfile, address_is_public, literal_ip
from open_hypergamy.errors import ConfigurationError

Resolver = Callable[[str], list[str]]

_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@]+@")


class EndpointRejected(Exception):
    """The proxy endpoint resolves somewhere it must not (rebinding, metadata, internal net)."""


def check_endpoint_addresses(profile: ProxyProfile, resolver: Resolver) -> list[str]:
    """Resolve the proxy host and require public addresses (unless explicitly local).

    Called before the proxy is used, not just at load time, so a name that later resolves to a
    private/metadata address (DNS rebinding) takes the profile out of rotation. Residual risk:
    the OS resolves again at connect time (ADR-012); pin by IP or use a literal address where
    that matters.
    """
    ip = literal_ip(profile.host)
    addresses = [str(ip)] if ip is not None else resolver(profile.host)
    if not addresses:
        raise EndpointRejected("proxy host did not resolve")
    if not profile.allow_private_endpoint:
        for a in addresses:
            if not address_is_public(a):
                raise EndpointRejected("proxy endpoint resolves to a non-public address")
    return addresses


def proxy_ssl_context(profile: ProxyProfile) -> ssl.SSLContext:
    """Verification is always on. A custom CA extends trust for this proxy only."""
    try:
        ctx = ssl.create_default_context(cafile=profile.ca_bundle)
    except (OSError, ssl.SSLError):
        raise ConfigurationError(
            f"proxy {profile.name}: ca_bundle is unreadable or not a valid PEM file"
        ) from None
    if ctx.verify_mode != ssl.CERT_REQUIRED or not ctx.check_hostname:  # pragma: no cover
        raise ConfigurationError("TLS verification must stay enabled for proxy connections")
    return ctx


def resolve_credentials(profile: ProxyProfile) -> tuple[str, str] | None:
    if profile.username_secret is None or profile.password_secret is None:
        return None
    user = keychain.get_secret(profile.username_secret)
    password = keychain.get_secret(profile.password_secret)
    if not user or not password:
        raise ConfigurationError(
            f"proxy {profile.name}: credential secrets are not set "
            "(environment variable or Keychain item)"
        )
    return user, password


def credential_state(profile: ProxyProfile) -> str:
    """For listings: never the values, never even their names' contents."""
    if profile.username_secret is None:
        return "none"
    ok = keychain.source_of(profile.username_secret) != "unset" and (
        profile.password_secret is not None
        and keychain.source_of(profile.password_secret) != "unset"
    )
    return "configured" if ok else "missing"


def scrub(text: str, profile: ProxyProfile | None = None, *secrets: str) -> str:
    """Remove the proxy address, userinfo and credential values from diagnostic text."""
    out = _USERINFO.sub(r"\1***@", text)
    if profile is not None:
        label = f"<proxy:{profile.name}>"
        for needle in (f"{profile.host}:{profile.port}", profile.host, profile.url):
            if needle:
                out = re.sub(re.escape(needle), label, out, flags=re.I)
    for s in secrets:
        if s and len(s) >= 3:
            out = out.replace(s, "***")
    return out


def check_ca_bundle_path(path: str | None) -> None:
    if path is not None and not Path(path).expanduser().is_file():
        raise ConfigurationError("proxy ca_bundle file not found")
