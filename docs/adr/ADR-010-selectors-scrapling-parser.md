# ADR-010: Per-source CSS/XPath and adaptive selectors (Scrapling parser)

Status: accepted. Extends LLD §7.4 (HTML adapter) and the `extraction_hints` field of the source schema (§6).

## Context

The HTML adapter extracted text with trafilatura and every link on the page. That is fine for articles but noisy for index pages (Cyber Valley: 70 links for 17 job pages) and cannot isolate a page region. `extraction_hints` was already in the schema and the database (migration 0002) but nothing read it.

## Decision

1. **Dependency: `scrapling` (core only, BSD-3, typed).** Only `scrapling.parser.Selector` is used (lxml + cssselect). The `scrapling[fetchers]` extra is deliberately **not** installed: it brings browser automation and fingerprint-spoofing components that this project does not use. All requests still go through `sources.fetch.Fetcher` (SSRF checks, scope, throttling, health/circuit breaker).
2. **`extraction_hints.selectors`** (`extraction/selectors.py`), validated at import time:
   ```yaml
   extraction_hints:
     selectors:
       adaptive: true
       title: {css: "h1"}
       text:  {css: "main"}
       links: {xpath: "//ul[@class='jobs']//a"}
   ```
   Each field takes exactly one of `css` / `xpath`; unknown keys are rejected. Selected values replace the defaults for that field only; unspecified fields keep the trafilatura/BeautifulSoup behaviour. Selected links still pass through `canonicalize_url` and the source's scope rules.
3. **A selector that matches nothing raises `ParseError`.** Per the "failure is not a fact" invariant it is a parser failure, never a clean empty scan.
4. **Adaptive selectors** (`adaptive: true`): on every successful match Scrapling stores the matched elements' fingerprints in `$OHG_HOME/cache/selectors.sqlite3` (keyed by `<source_key>:<field>`). If the selector later stops matching, the stored fingerprint is used to relocate the element. A relocated result is **best-effort** (it can recover fewer elements than were saved) and is flagged in `PageObservation.meta["selectors"] = "relocated:<fields>"`. With no stored fingerprint, or no storage path, a miss is still a `ParseError`; nothing is guessed.
5. `SourceRecord.extraction_hints` and `FetchContext.selector_storage` carry the data to the adapter. No migration is needed.

## Not implemented, on purpose

- **Stealth browser fingerprinting, CAPTCHA/Cloudflare challenge bypass, proxy rotation to evade blocking.** These are access-control circumvention. They conflict with the README responsible-use notice, `CLAUDE.md` invariant 6 and the `allow_captcha_bypass` validator, and with ADR-009, which treats a 403 or a challenge page as a hold for human review. A source that serves a challenge stays held.
- **JavaScript rendering.** Needs a browser dependency and binary download, and the per-source allowlist from the invariants. Deferred; it would be a non-stealth Playwright adapter for allowlisted sources only.
- **Concurrent crawling across sources.** `HostGate` (ADR-009) makes the fetcher safe for it, but the orchestrator is still sequential because writes and per-source transactions would need rework.
- Adaptive throttling and retry/recovery already exist (ADR-009); this ADR does not change them.

## Consequences

- Index pages can be reduced to the region and links that matter, which cuts crawl load and noise.
- A site redesign can silently shift what a selector matches. Adaptive mode recovers some cases and flags them; otherwise the source fails loudly and shows up in `sources failures`.
- `uv.lock` gains scrapling, cssselect, orjson and w3lib.
