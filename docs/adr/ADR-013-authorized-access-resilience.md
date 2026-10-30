# ADR-013: Authorized access resilience (alternative channels, not circumvention)

Status: accepted. Builds on ADR-009 (health/breaker) and ADR-012 (egress proxies). No migration.

## Context

Opportunity capture should survive a publisher becoming unreachable, without ever turning an access restriction into an arms race. The rule from ADR-012 stands: **a destination's 401/403/429/451, CAPTCHA, challenge or other access-denied answer never causes rotation, failover or any identity change**, and the source stays in the existing cooldown / `BLOCKED_REVIEW` machinery. Resilience therefore comes from (a) infrastructure failover between *trusted* proxies, (b) *official* alternative channels, (c) the publisher's *permission*, (d) user-supplied material, and (e) never losing what was already found.

## Decision

1. **Official machine-readable channels.** New `ical` (RFC 5545 VEVENT, own minimal parser) and `json_feed` (JSON Feed 1.x) adapters next to RSS/Atom. Entries are discovery hints (`feed_metadata`): they can never confirm a fact; DTSTART/`date_published` stay in `FeedEntry.published`, not in deadline evidence. Events without a URL are skipped (nothing to verify against).
2. **JavaScript-only pages are classified, not executed.** `detect_js_shell` (conservative: almost no visible text AND scripts AND a `<noscript>` JavaScript demand or an empty framework mount) makes the fetcher raise `RenderingRequired` (`rendering_required`). It is never retried and holds the source (`BLOCKED_REVIEW`, category `rendering_required`) so an operator picks an official feed/API/iCal channel or the existing Playwright allowlist. **No browser rendering was built** (CLAUDE.md: Playwright adapter still unimplemented; such sources stay `skipped`).
3. **Alternative-channel discovery is offline.** `ohg sources alternatives KEY` reads the registry and the *cached body of the last successful observation* and lists channels the publisher itself advertises (`<link rel=alternate>` feeds/calendars, same-site `.ics`/`.rss`/`/feed` links) plus already-registered siblings. It fetches, registers and enables nothing; every suggestion needs a terms review and a sources YAML import. No SERP scraping, no third-party lookup.
4. **Publisher permission workflow.** `ohg sources permission-request KEY` prints (sends nothing) a request stating scope, interval, pacing, User-Agent, the no-bypass/no-rotation promise and, if configured, the profile's `egress_ips` (public addresses the operator controls; documentation only, never used for routing or trust). A publisher-approved allowlist is expressed by *assigning the source to the approved profile(s)* (`proxy.assignments`). If the publisher blocks that identity the source is held like any other; OHG never searches for an identity that works. Recording permission in the database is not built.
5. **User-provided imports.** `ohg import newsletter FILE` (.eml/.html/.txt, ≤5 MB) extracts opportunity-looking links (tracking parameters removed, unsubscribe/mailto dropped, ≤50) and adds each as a manual lead through the existing `candidates add` path: SSRF-checked, never auto-verified, deduplicated by URL then fingerprint. `--dry-run` lists leads without fetching.
6. **Cross-source dedupe** is the existing identity model (canonical URL, then `title|organizer|edition` fingerprint). Scenario tests assert that a programme found through the HTML index and through a later-registered feed yields one candidate, one program and one edition.
7. **Unavailability never deletes.** Failures only touch health columns (invariant 3); scenario tests snapshot editions, deadlines (with fact status), claims and candidates before and after 403, CAPTCHA, JS-shell, proxy-outage and 503 runs and require equality. Facts age into `stale` through the existing freshness rules.
8. **Recall measurement.** `ohg measure recall --truth FILE` counts a truth item as captured if *any* channel produced a candidate (URL match, else fingerprint), reports per-channel counts, the missed list and a Wilson 95 % interval. The truth set must carry `compiled_by`, `method` and `independent: true` (an attestation OHG cannot verify). Verdicts: `UNVERIFIED` (no attestation), `INSUFFICIENT SAMPLE` (n < 100), `CONSISTENT WITH TARGET` only if the 95 % lower bound ≥ target on an attested set, else `NOT DEMONSTRATED`. Even 100/100 yields a lower bound of 96.3 %, i.e. `NOT DEMONSTRATED` at 97 %. **The 97 % target has not been measured; no ground truth exists in this repository.**

## Simulated environments (tests/simulation)

`Publisher` + `SimProxy` model IP blocking, publisher-approved allowlists, rate limiting (429 + Retry-After), CAPTCHA/challenge pages, geo restriction (451), JS shells, downtime and proxy failure, all in-process and deterministic. Scenarios check detection, classification, recovery and fallback end-to-end through `run_discovery` and the real fetcher, pool, health and persistence code. They validate *our* logic; they say nothing about how any real site behaves and nothing here targets or probes a real third party.

## Not done / limits

- No browser rendering, no generic JSON/REST "official API" adapter (only JSON Feed), no persisted permission records, no automated alternative-source search beyond the offline suggestions, no scheduling of newsletter imports.
- `sources probe` (YAML batch check) and manual `candidates add` fetch outside an `egress_scope`, so they are direct by design.
- A restriction pin (ADR-012) lasts for the process; changing the assignment takes a new process (or `release_restrictions()`), which is the intended operator step after a permission change.
- Newsletter import's per-lead loop reuses `candidates add` and is covered by extractor and dry-run tests, not by a live multi-lead run.
- Recall depends entirely on the operator's truth set; matching is by URL/identity fingerprint and a match means a candidate exists, not that its dates are verified.
