# ADR-008: robots.txt is informational, not enforced

Status: accepted. Supersedes the robots rules in LLD §7.5 and ADR-003 item 5 (`obey_robots_txt` is removed).

## Decision

Crawl policy is owned by OpenHypergamy's source configuration and policy engine, not by a site's robots.txt.

1. Fetching a page no longer requests or evaluates robots.txt. `Disallow` and `Crawl-delay` never reject or delay a request.
2. `Fetcher.robots_info(url)` can still retrieve and parse robots.txt as informational metadata (cached per origin, never raises). `ohg sources probe` uses it to print a note when robots.txt disallows a URL. Nothing else consults it.
3. robots.txt is not treated as legal authorization or prohibition. Terms, copyright and database rights remain the operator's responsibility; the per-source `terms_review_note` / `robots_policy_checked_at` activation gate is unchanged.

## Unchanged

SSRF checks, domain allowlists and `deny_paths`, size/redirect caps, the per-host minimum interval (`app.per_host_min_interval_seconds`) and concurrency, retries with `Retry-After` for 408/429/5xx (long waits are refused), and the ban on login, CAPTCHA and paywall circumvention.
HTTP 403 is not retried and not worked around; it is recorded as a source failure and surfaces in `sources audit`/`failures` for review (since ADR-009 it also puts the source on hold until `ohg sources unblock`).

## Consequences

- A site that disallows crawling in robots.txt may still be fetched. Operators decide per source, using the terms review note.
- Operators should keep `fetch_interval_hours` and the per-host interval conservative; `Crawl-delay` values are visible via `robots_info` but are not applied.
- Existing settings files that contain `crawling.obey_robots_txt` get the usual unknown-key warning and can drop the line.
