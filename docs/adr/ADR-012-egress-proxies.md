# ADR-012: Operator-controlled egress proxies (no public proxy lists, no identity switching)

Status: accepted. Adds migration 0008 and the `egress/` package. Builds on ADR-003 (fetch), ADR-008 (robots informational) and ADR-009 (source health). Invariants 5, 6 and 8 in CLAUDE.md are unchanged.

## Context

An operator may need authorized egress paths for public-source acquisition (a corporate or VPN egress, a proxy they run). `TheSpeedX/PROXY-List` was evaluated and **rejected**: it is an unvetted list of anonymous open proxies (no operator identity, no license, no validation, collection method undisclosed). Any exit can read plaintext, inject content into pages that feed extraction and the LLM, or MITM TLS if verification were ever relaxed. Public lists are also dominated by already-blocked addresses, so using them mostly produces 403/429 and invites rotation to evade restrictions, which invariant 6 forbids. No public list is ever imported, trusted or fetched.

While reviewing the fetcher we also found `httpx.Client` defaulted to `trust_env=True`, so `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` in the environment would silently reroute traffic. That is fixed for every client (crawler, Telegram, LLM gateway).

## Decision

### Architecture

```
source check ──egress_scope(source_key)──▶ Fetcher.fetch ─▶ validate URL (SSRF, scope) ─▶ host cooldown
                                                │
                              EgressPool.acquire(source, host)   ← profile selection + health
                                                │                  (never returns "direct" for an assigned source)
                       HostGate.slot(destination host)  ← unchanged; keyed by destination, never by proxy
                                                │
              httpx.Client per profile (own cookie jar/pool, trust_env=False, TLS verified)
                                                │
          destination answered ─▶ existing status/retry/barrier/circuit-breaker logic (identity never changes)
          proxy failed (classified) ─▶ report_failure ─▶ bounded failover to another trusted profile, else EgressUnavailable
```

- `egress/settings.py`: strict Pydantic models (`extra="forbid"`, input never echoed). `egress/security.py`: endpoint address policy, TLS context, secret lookup, `scrub`. `egress/classify.py`: proxy-fault vs destination classification. `egress/pool.py`: health, selection, affinity, failover, restriction pinning, per-check `EgressReport`. `egress/transport.py`: one isolated client per profile. `cli_proxy.py`: `ohg proxy list|check`.
- **Default is direct.** `proxy.enabled: false`. A source uses a proxy only if it appears in `proxy.assignments` (or `default_profiles`, empty by default). Traffic outside an `egress_scope` (manual leads, Telegram, LLM, Keychain) is always direct and uses separate clients that accept no proxy parameter.
- **Supported:** `http://` (forward/CONNECT), `https://` (TLS to the proxy, then CONNECT), `socks5://` (via `httpx[socks]`/`socksio`; hostnames are sent to the proxy, i.e. remote DNS). No SOCKS4, no auto-discovery.
- **Selection:** `round_robin` or `least_failure` (fewest consecutive/total failures, then lowest latency). `affinity: source` keeps a source on one profile until it fails (default); `none` rotates per fetch call. Retries and redirects of one fetch call stay on one route. Manual selection is `egress_scope(..., forced_profile=…)` / `ohg proxy check --profile`: no rotation, no failover.
- **Health:** `healthy → degraded` on a failure, `→ unhealthy` after `failure_threshold` consecutive failures (immediately for a rejected endpoint address), cooldown `cooldown_seconds · 2ⁿ` capped at `max_cooldown_seconds`. After the cooldown the profile re-enters only if a probe GET of `proxy.health_check_url` through *that* proxy succeeds (throttled by the same HostGate); otherwise the cooldown doubles. Without a passing probe it stays out. A real success returns `degraded → healthy`. A proxy refusing a destination (`DENIED`) is a policy answer and does not count as an outage.
- **Failover is allowed only for:** connect refused/unavailable, proxy connect timeout, proxy DNS failure, proxy auth failure (407 or SOCKS auth error), CONNECT/SOCKS 502/503/504, malformed proxy replies, endpoint-address rejection. It is bounded by `max_failovers` (≤5), never to a profile already tried in that fetch, and failover attempts re-take a destination slot.
- **Never triggers failover or rotation:** any destination response (401, 403, 429, 451, 5xx, 200 challenge/CAPTCHA/login pages), read timeouts and mid-stream protocol errors (not evidence about the proxy), TLS verification failures (ambiguous proxy-vs-destination: fail closed), proxy ACL denial (`SourcePolicyDenied`, `blocked_policy`). After a 401/403/429/451 or a barrier, the destination host is **pinned** to the identity that saw it for the rest of the process: no rotation, and if that profile later fails the fetch raises `EgressUnavailable` rather than switching. `Retry-After`, host cooldown and the source circuit breaker/holds (ADR-009) are untouched; the destination status is only *recorded*.
- **No direct fallback:** an assigned source with no usable profile fails with `EgressUnavailable` (`egress_unavailable`, categorized as a transient `network` failure so the source breaker backs it off). It is never retried directly.
- **Diagnostics (migration 0008):** `source_check_egress` per check that used a proxy: profile name, rotation/failover counts, proxy latency, destination status, JSON detail (profiles used, proxy failure categories by kind, proxy health by name). Names and counters only. Circuit-breaker state remains in the existing `sources` health columns. `ohg proxy list/check` show health and credential *state*.

### Threat model

| Threat | Control | Residual |
|---|---|---|
| Public/unvetted proxy trusted | No list import; profile needs `trusted: true` **and** host in `trusted_endpoint_hosts`; unknown keys fail config | Operator can still trust a bad host |
| SSRF via proxy endpoint config | Scheme allowlist; loopback/private/link-local/metadata endpoints need `allow_private_endpoint: true`; host re-resolved before use and rejected if non-public (rebinding) | Name is resolved again by the OS at connect time (TOCTOU); use a literal IP or a pinned name for high assurance |
| SSRF to internal/metadata via the destination | Every URL and redirect hop validated locally (existing `validate_public_url`, scope) before any proxy sees it | The proxy resolves the destination itself, so local DNS validation does not bind it: **the proxy must enforce destination ACLs** (deployment requirement) |
| Credential leakage | Secrets only by name (`OHG_PROXY_*`) from env/Keychain; passed as structured auth, never in URL/YAML/SQLite/argv; `scrub` on messages; config errors never echo input; listings show only `configured/missing` | Env vars are visible to same-user processes |
| MITM of proxy/destination TLS | Verification and hostname checking always on; custom CA applies to the proxy only, never to destinations | `http://`/`socks5://` to a remote endpoint is cleartext to the proxy; needs `allow_plaintext: true` (use inside a tunnel); an `https://` destination through CONNECT is end-to-end, an `http://` one is readable by the proxy |
| Hostile proxy content | Size, type, redirect, scope and barrier checks run on proxied responses; proxy cannot widen scope; nothing from a proxy can set `confirmed_official` | A malicious proxy can forge page content for a plain-http destination or deny service |
| Ambient proxy hijack | `trust_env=False` on crawler, Telegram, LLM and proxy clients | — |
| Cross-contamination | Per-profile clients (cookies/pools not shared); sensitive clients have no proxy parameter; unscoped traffic direct | A forgotten call site outside `egress_scope` goes direct (see below) |
| Rate-limit evasion | HostGate keyed by destination host; adaptive delay and cooldowns persist across profiles; dead-proxy attempts don't feed pacing | Multiple identities inherently dilute per-IP limits on the destination: operator must not use rotation to exceed what a site permits |
| Access-control circumvention | Destination responses never change identity; restricted hosts pinned; no CAPTCHA/challenge handling, fingerprint or UA changes | — |

### Configuration example (not applied anywhere)

```yaml
proxy:
  enabled: true
  selection: least_failure          # or round_robin
  affinity: source
  trusted_endpoint_hosts: [edge1.example.net, edge2.example.net]
  health_check_url: https://health.example.net/ok
  max_failovers: 2
  profiles:
    - name: edge1
      url: https://edge1.example.net:8443       # no credentials in the URL
      trusted: true
      username_secret: OHG_PROXY_EDGE1_USER     # env var or Keychain item NAME
      password_secret: OHG_PROXY_EDGE1_PASS
      ca_bundle: /etc/ohg/edge-ca.pem           # optional; trusted for this proxy only
    - name: edge2
      url: https://edge2.example.net:8443
      trusted: true
  assignments:
    example-student-programmes: [edge1, edge2]  # everything else stays direct
```

Credentials: `export OHG_PROXY_EDGE1_USER=…` (or a Keychain item with that account name). Never on a command line.

### Deployment requirements

1. The proxy fleet must enforce its own destination ACL (deny RFC1918, loopback, link-local, `169.254.169.254`, cloud metadata names), because the proxy resolves destinations.
2. Use `https://` proxy endpoints, or run `http`/`socks5` only inside a protected tunnel (`allow_plaintext`).
3. Per-profile credentials; rotate them; keep them out of shell history and CI logs.
4. Deploy proxy endpoints on public, stable addresses you control; avoid names an attacker can re-point.
5. Keep `app.per_host_min_interval_seconds` ≥ 3 s; do not raise concurrency because more egress identities exist.
6. Run `ohg proxy check` after any change. It exits 4 if a probe fails.

## Not done / residual risks

- Connect-time DNS pinning for hostname endpoints (needs a custom transport); the pre-use re-resolution narrows but does not close the window.
- Health state is process-local; only per-check diagnostics persist. A new process starts every profile healthy (probing happens on first failure).
- `ohg proxy` has no runtime enable/disable; use `enabled` in config (re-read each invocation).
- Call sites that fetch source-owned pages must run inside `egress_scope(source_key)`. Done for discovery checks, recheck and the candidate evidence fetch; new code that fetches for a source must do the same or it goes direct. `candidates add` (manual leads) and `robots_info` outside a scope are intentionally direct.
- A 407 from a *forward* (plain-http destination) proxy is treated as a proxy fault; other proxy-generated 4xx/5xx on that path are indistinguishable from destination answers.
- TLS verification failures are not attributed to proxy vs destination at request time; the health probe attributes them to the proxy.
- `http_proxy` forward-proxy behaviour and real SOCKS5 servers were exercised only through fakes and one local TLS handshake test, not against real proxy software.
- Tests prove the stated controls behave as designed; they are not a security audit. No penetration test was performed.
