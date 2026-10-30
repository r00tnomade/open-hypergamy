# ADR-009: Source health, circuit breaker and fetch resilience

Status: accepted. Extends LLD §7.1–7.2 (fetch rules) and §6.5 (source health); adds migration 0006.

## Context

The fetcher already sent conditional requests, retried 408/429/5xx a bounded number of times and never let a failure touch facts. However, a 403 or a CAPTCHA page was retried on every backoff cycle forever, a 200 challenge or login page was ingested as content, HTTP-date `Retry-After` was ignored, nothing stopped other sources on an overloaded host from being hit in the same run, and the only health signal was `failure_streak`.

## Decision

1. **Health state is derived, not stored** (`sources/health.py`): `healthy`, `degraded`, `cooldown`, `blocked_review`, `stale`, `disabled`. Migration 0006 stores only the inputs that cannot be derived from history: `cooldown_until`, `last_error_category`, `blocked_reason`, `blocked_at`. `last_successful_ingestion_at`, rates, status mix, latency and change counts are computed from `source_check_runs`/`source_observations` at report time.
2. **Error categories** (`ErrorCategory`) classify every failed check: network, rate_limited, server_error, access_denied (401/403/451), access_barrier, not_found, gone, http_error, content, policy, partial, internal.
3. **Per-source circuit breaker**, applied in `SourceRepository.record_check`:
   - 429 and 5xx open it immediately; other transient failures open it after `crawling.cooldown_after_failures` (3) in a row. Cooldown = the existing exponential backoff (1 h, 2 h, 4 h …), extended to `Retry-After`, capped at `crawling.max_cooldown_hours`.
   - While cooling down a source is neither scheduled nor runnable by `run discovery --source-id`, and deadline rechecks skip it.
   - 401/403/451, a 200 access barrier, 410, or `crawling.not_found_review_after` (2) consecutive 404s put the source on **hold for review**. A hold never expires; `ohg sources unblock <key>` ends it after a human has looked. The streak is kept, so an unchanged 403 re-holds it at once.
   - Any successful check closes the breaker and clears the category.
4. **Access-barrier detection** (`sources/barriers.py`): a 200 response is rejected with `AccessBarrier` (never retried) when it redirected to a login path, carries a vendor block-page marker, or has a challenge, access-denied or login (with a password field) *title*. Generic words and vendor beacons on ordinary pages do not trigger it. This is detection only; nothing is solved or bypassed.
5. **Transport** (`sources/fetch.py`):
   - `HostGate`: per-host concurrency slots (`app.per_host_max_concurrency`, default 1) and thread-safe spacing.
   - AutoThrottle-style adaptive delay (Scrapy's algorithm, reimplemented): `delay ← max(floor, (delay + latency) / 2)`. 429/503 double the delay, other errors never reduce it, and the 3 s `per_host_min_interval_seconds` stays a hard floor. The cap is `app.max_host_delay_seconds`.
   - Retry backoff gets ±50 % jitter. `Retry-After` accepts HTTP-dates.
   - After a 429/503 survives retries (or asks for more than 30 s), the whole host is paused for the rest of the process (`app.host_cooldown_seconds`, or longer if `Retry-After` says so) and further requests fail fast with `HostCoolingDown`, without hitting the network.
   - `elapsed_ms` is now network time only. It is recorded in `source_check_runs` together with `retry_count` and `bytes_received`, which were previously always NULL.
6. **Crawler identity**: `User-Agent: OpenHypergamy/0.1 (+<app.crawler_info_url>; <app.crawler_contact>)`. The contact can also come from `OHG_CRAWLER_CONTACT`. A user agent containing browser tokens (`Mozilla/`, `Chrome/`, …) is rejected at config load.

## Libraries evaluated (2026-10-30, Python 3.12–3.14)

| Library | Licence / latest | Decision |
|---|---|---|
| Scrapy 2.19 | BSD-3, active | **Rejected** as a dependency (Twisted reactor, ~35 deps, would replace the fetcher and its SSRF/scope chain). AutoThrottle's algorithm is borrowed in `HostGate`. |
| feedparser 6.0.14 | BSD-2, active | **Kept** (already used). It has no JSON Feed support; no source needs JSON Feed yet. |
| trafilatura 2.3.1 | Apache-2.0, active | **Kept** (already used for main-text extraction, with a BeautifulSoup fallback). |
| selectolax 1.0.2 | MIT, active | **Not added.** Parsing is not the bottleneck when every host is throttled to ≥3 s, and a second HTML parser would duplicate BeautifulSoup. Its 3.14 classifier is also missing. |
| Playwright 1.64 | Apache-2.0, active | **Not added.** It stays behind the per-source allowlist and is unimplemented. It is not to be used for anti-bot evasion. |

No dependency was added.

## Not done / limits

- The orchestrator still checks sources sequentially. `HostGate` makes the fetcher safe for concurrent use, but no thread pool was introduced (SQLite writes and per-source transactions would need rework).
- A 304 on an index page still does not re-crawl its children (unchanged from ADR-003). Cached bodies are not re-parsed on a 304.
- Barrier heuristics are English-centric and title-based. A barrier page with an unusual title is ingested and then surfaces as unparseable content rather than as a hold.
- The in-run host cooldown and adaptive delays live in memory only and reset between processes. The persisted per-source cooldown is what spans runs.
