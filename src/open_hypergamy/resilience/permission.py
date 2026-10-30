"""Publisher permission request text (ADR-013). Generated locally; nothing is sent.

Used when an operator wants a publisher's explicit approval: to crawl politely at a stated
rate, and optionally to allowlist OHG's *stable* egress addresses. Addresses come from the
operator's own configured profiles (public IPs the operator controls), never from third parties.
"""

from __future__ import annotations

from open_hypergamy.config import LoadedConfig
from open_hypergamy.sources.base import SourceRecord


def render_request(
    cfg: LoadedConfig, source: SourceRecord, egress_addresses: dict[str, list[str]]
) -> str:
    app = cfg.settings.app
    paths = ", ".join(source.allow_paths) or "(whole site within the allowed domains)"
    lines = [
        f"Subject: Request for permission to read public opportunity listings on {source.domain}",
        "",
        "Hello,",
        "",
        "I run OpenHypergamy, a small single-user tool that reads publicly listed research and "
        "education opportunities (internships, summer schools, fellowships, calls) and reminds "
        "me about deadlines. I would like your permission to fetch the following public pages "
        "automatically, and I would appreciate an official feed, calendar or API if you offer one.",
        "",
        f"  Source:            {source.name}",
        f"  Starting URL:      {source.canonical_url}",
        f"  Paths in scope:    {paths}",
        f"  Polling interval:  every {source.fetch_interval_hours} hours (conditional requests)",
        f"  Request pacing:    at most one request per {app.per_host_min_interval_seconds:g} s "
        "per host, one at a time, honouring Retry-After",
        f"  User-Agent:        {app.effective_user_agent()}",
        "  Behaviour:         no login, CAPTCHA or paywall bypass; no rotating identities; "
        "I stop on 401/403/429 and ask you before retrying",
        "",
    ]
    if egress_addresses:
        lines += [
            "If you keep an allowlist, my requests will come only from these addresses:",
            *(f"  {n}: {', '.join(a)}" for n, a in sorted(egress_addresses.items())),
            "",
        ]
    lines += [
        "Please reply with approval, restrictions (paths, rates, hours) or an alternative channel.",
        "I will record your answer and follow it.",
        "",
        f"Contact: {app.crawler_contact or '(set app.crawler_contact / OHG_CRAWLER_CONTACT)'}",
    ]
    return "\n".join(lines) + "\n"
