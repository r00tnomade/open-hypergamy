# ADR-003 — Milestone 2 fetch pipeline decisions

**Status:** Accepted · **Date:** 2026-10-29

1. **Migration 0002** adds `discovery_policy_json`, `extraction_hints_json`, `discovery_only`, `policy_override_at` to `sources`. LLD §6 requires these concepts but the 0001 schema has no columns for them; 0001 stays immutable.
2. **`PageObservation` URLs are canonical `str`, not `HttpUrl`.** Pydantic's `HttpUrl` re-normalizes (e.g. appends `/`), which would silently change canonical identity. Added `entries`, `meta`, cache paths and `depth` fields.
3. **Policy review gate.** A source is activated at import only if `robots_policy_checked_at` and a non-empty `terms_review_note` are present, or `--override-policy-review` is given (stored in `policy_override_at`). `ohg sources add` always creates a disabled `review_required` source.
4. **Discovery-only** = T4/T5 with no documented `authority_scope`; stored in `discovery_only`.
5. **Robots (superseded by ADR-008):** 4xx robots.txt = allow; 5xx/network error = do not crawl that origin this run (recorded as `blocked_policy`, not a source failure). Cached per origin per process.
6. **Failures vs. policy:** `blocked_policy` and `skipped` never increment `failure_streak`. Real failures back off 1h, 2h, 4h… capped at the source's fetch interval. A failed check never alters etag, content hash, `last_success_at` or stored observations.
7. **304 handling:** the seed page returns `not_modified`; children behind an unchanged index are not re-crawled (known limitation; **superseded by ADR-011**, which tracks and revalidates children on their own schedule). Child pages use stored validators from their latest observation.
8. **Redirects** are followed manually; every hop is re-validated (scheme, DNS→public IP, domain allowlist, deny paths). Limitation: DNS is checked before connect, not pinned, so a rebinding resolver is not fully excluded.
9. **Not implemented yet:** iCalendar and Playwright adapters (such sources are recorded as `skipped`), per-host concurrency (runs are sequential), body-cache retention pruning.
10. **Sequential execution** keeps per-host throttling trivially correct; `max_concurrent_hosts` is reserved for later.
