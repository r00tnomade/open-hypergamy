"""URL canonicalization and SSRF-safe validation (LLD §7.3, §8.2)."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from open_hypergamy.errors import SourcePolicyDenied

Resolver = Callable[[str], list[str]]

_TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "yclid",
    "_hsenc",
    "_hsmi",
    "mkt_tok",
    "ref_src",
}
_DEFAULT_PORTS = {"http": 80, "https": 443}
_LOCAL_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home.arpa")


def default_resolver(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise SourcePolicyDenied(f"DNS resolution failed for {host}: {e}") from e
    return sorted({str(i[4][0]) for i in infos})


def _is_tracking(name: str) -> bool:
    n = name.lower()
    return n.startswith("utm_") or n in _TRACKING_PARAMS


def canonicalize_url(url: str, base: str | None = None) -> str:
    """Canonical identity form. Raises SourcePolicyDenied for unusable URLs.

    Lowercases scheme/host (IDNA), drops default ports, fragments, tracking parameters and
    credentials-bearing URLs are rejected. Trailing slashes are preserved except for empty paths.
    """
    full = urljoin(base, url.strip()) if base else url.strip()
    parts = urlsplit(full)
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS:
        raise SourcePolicyDenied(f"unsupported URL scheme: {scheme or '(none)'}")
    if parts.username or parts.password:
        raise SourcePolicyDenied("URLs with embedded credentials are not allowed")
    host = (parts.hostname or "").lower()
    if not host:
        raise SourcePolicyDenied("URL has no host")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as e:
        raise SourcePolicyDenied(f"invalid hostname: {host!r}") from e
    try:
        port = parts.port
    except ValueError as e:
        raise SourcePolicyDenied("invalid port") from e
    netloc = f"[{host}]" if ":" in host else host
    if port and port != _DEFAULT_PORTS[scheme]:
        netloc += f":{port}"
    query = urlencode(
        [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)]
    )
    return urlunsplit((scheme, netloc, parts.path or "/", query, ""))


def _ip_blocked(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return not addr.is_global


def check_static_host(host: str) -> None:
    """Import-time check that needs no DNS: literal IPs and obviously local names."""
    h = host.strip("[]").lower()
    try:
        if _ip_blocked(h):
            raise SourcePolicyDenied(f"non-public IP address is not a valid crawl target: {h}")
        return
    except ValueError:
        pass  # not a literal IP
    if h == "localhost" or h.endswith(_LOCAL_SUFFIXES) or "." not in h:
        raise SourcePolicyDenied(f"local hostname is not a valid crawl target: {h}")


def validate_public_url(
    url: str,
    *,
    permitted_schemes: Iterable[str] = ("https", "http"),
    resolver: Resolver = default_resolver,
) -> str:
    """Canonicalize and verify every resolved address is public (call again on each redirect)."""
    canonical = canonicalize_url(url)
    parts = urlsplit(canonical)
    if parts.scheme not in set(permitted_schemes):
        raise SourcePolicyDenied(f"scheme not permitted: {parts.scheme}")
    host = parts.hostname or ""
    check_static_host(host)
    try:
        ipaddress.ip_address(host)
        return canonical  # literal public IP, already checked
    except ValueError:
        pass
    for ip in resolver(host):
        if _ip_blocked(ip):
            raise SourcePolicyDenied(f"{host} resolves to non-public address {ip}")
    return canonical


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()
