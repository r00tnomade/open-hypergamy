"""Crawl scope and robots.txt policy (LLD §7.3, §7.5)."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from open_hypergamy.errors import SourcePolicyDenied
from open_hypergamy.sources.urls import host_of


@dataclass(frozen=True)
class Scope:
    allowed_domains: tuple[str, ...]
    allow_paths: tuple[str, ...] = ()
    deny_paths: tuple[str, ...] = ()

    def domain_ok(self, url: str) -> bool:
        host = host_of(url)
        return any(host == d or host.endswith("." + d) for d in self.allowed_domains)

    def path_denied(self, url: str) -> bool:
        path = urlsplit(url).path or "/"
        return any(path.startswith(p) for p in self.deny_paths)

    def path_allowed(self, url: str) -> bool:
        path = urlsplit(url).path or "/"
        return not self.allow_paths or any(path.startswith(p) for p in self.allow_paths)

    def check_fetchable(self, url: str) -> None:
        """Domain allowlist + deny paths; applies to the seed URL and every redirect hop."""
        if not self.domain_ok(url):
            raise SourcePolicyDenied(f"{host_of(url)} is outside the source's allowed domains")
        if self.path_denied(url):
            raise SourcePolicyDenied(f"path denied by source policy: {urlsplit(url).path}")

    def link_in_scope(self, url: str) -> bool:
        """Whether a discovered link may be crawled (adds allow_paths on top of fetchable)."""
        return self.domain_ok(url) and not self.path_denied(url) and self.path_allowed(url)


class RobotsRules:
    """Parsed robots.txt for one origin; `None` rules means allow-all (4xx robots)."""

    def __init__(self, lines: list[str] | None) -> None:
        self._parser: RobotFileParser | None = None
        if lines is not None:
            self._parser = RobotFileParser()
            self._parser.parse(lines)

    def allowed(self, user_agent: str, url: str) -> bool:
        return True if self._parser is None else self._parser.can_fetch(user_agent, url)


def robots_agent_token(user_agent: str) -> str:
    """`OpenHypergamy/0.1 (+...)` -> `OpenHypergamy`."""
    return user_agent.split("/", 1)[0].split(" ", 1)[0]
