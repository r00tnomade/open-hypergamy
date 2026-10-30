# ADR-011: Child pages are tracked and revalidated independently of the index

Status: accepted. Supersedes ADR-003 item 7 ("children behind an unchanged index are not re-crawled"); adds migration 0007. Builds on ADR-009 (source health) for cooldowns and holds.

## Context

An HTML source with `follow_internal_links` fetched its child pages only while crawling links of a *changed* index. When the index answered 304, the adapter returned just the seed, so a changed programme page behind an unchanged index list was never noticed. Child state existed only implicitly (the latest observation per URL), which also meant there was nowhere to record that a child had failed, vanished or been refused. 304 responses from children did not count towards `max_pages_per_run`, and the adapter read time from the fetcher's clock instead of the run's.

## Decision

1. **`source_pages`** (migration 0007) holds one row per followed URL per source: depth, status (`active`, `missing`, `held`, `invalid`), validators (ETag, Last-Modified), content hash, `last_checked_at`, `last_changed_at`, `next_check_at`, failure count, last HTTP status/error. Observations remain the evidence log; this table is revalidation state only. Pages observed before the migration are adopted and become due on the first run.
2. **Each child has its own freshness window**: `discovery_policy.child_recheck_hours`, default the source's `fetch_interval_hours`. A page is *due* when it is `active` and `next_check_at` has passed.
3. **One work queue per run** (`HtmlAdapter.fetch`): in-scope links of the index (only when the index returned 200) followed by every due tracked child, oldest check first (never-checked pages first). A 304 index therefore still revalidates due children. Fresh known children are skipped without a request, even when the index changed.
4. **Conditional requests**: a child sends the ETag/Last-Modified stored on its own row (fallback: its latest observation). A child 304 renews its window and changes nothing else; a 304 without validators keeps the stored ones.
5. **Limits and safety are unchanged and apply to every request**: `max_pages_per_run` counts all requests (seed, 304s and failures included) so revalidation cannot exceed it; `max_depth`, SSRF validation, domain/path scope and the per-host gate all apply. The number of remembered pages per source is capped (`app.max_tracked_pages_per_source`, 200). Discovered links beyond the page limit are remembered and fetched on later runs instead of being lost.
6. **Source cooldown and holds come first**: a source on cooldown or hold is neither scheduled nor runnable manually, and its seed is fetched before any child, so a failing seed ends the check before a single child request. If the host starts refusing mid-run (429/503 survived retries), `HostCoolingDown` stops the child loop; the remaining pages stay due. Child trouble never trips the source's own breaker (the check is `partial`, streak 0).
7. **Failures never delete anything.** Transient failures back off (1 h, 2 h … up to the page's window, `Retry-After` honoured, capped by `crawling.max_cooldown_hours`). 410, or `crawling.not_found_review_after` consecutive 404s → `missing`. 401/403/451 or a 200 challenge/login page → `held`. A link that has left the current scope → `invalid` (no request is sent). `missing` pages get one retry when a changed index lists them again; `held`/`invalid` wait for an operator (`ohg sources unblock` reactivates all non-active pages). Observations, candidates, editions, deadlines and claims are untouched; their evidence simply ages into `stale` through the existing freshness rules.
8. **Reporting**: `sources audit` / `report sources` expose `pages_tracked`, `pages_due`, `pages_missing`, `pages_held`, `pages_invalid`, and the audit lists missing/held/invalid pages as issues.
9. A new observation from a child now also sets the source's `last_content_change_at`. On a 304 index the source keeps its own ETag/Last-Modified/hash instead of adopting the (empty) 304 response's.
10. `FetchContext.clock` carries the run's injected clock; the adapter uses it for due checks.

## Not done / limits

- Sitemap and RSS adapters never fetched child pages and are unchanged. Their listed URLs are still followed by the candidate pipeline's own evidence fetch.
- `child_recheck_hours` is per source, not per page. A page cannot be given its own interval.
- An operator cannot yet release a single held page; `unblock` releases the whole source.
- Pages deeper than `max_depth` after a policy tightening are skipped but not marked.
- Revalidation is sequential, like the rest of discovery (see ADR-009).
