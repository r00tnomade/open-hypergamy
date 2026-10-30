# Changelog

All notable changes are listed here. The project is pre-1.0, so anything may still change.

## [Unreleased]

### Added
- `ohg onboard`: a local GUI for first-run setup and later edits (profile, opportunity preferences, a matching preview on fictional examples, optional Telegram and AI gateway checks). Loopback only, one-time launch link, CSRF/Origin/Host checks, strict CSP, secrets only in the Keychain. Resumable via `<home>/onboarding.json` (ADR-014).
- Profile fields `display_name`, `academic.institution` and `preferences.categories`; scoring `score-v2` ranks preferred categories higher and accepts `WORLDWIDE` as a region (ADR-014).
- GUI-managed settings file `<home>/settings.yaml`, used only when no hand-written settings file is present (ADR-014).
- Per-source CSS/XPath selectors with optional adaptive relocation via Scrapling's parser (`extraction_hints.selectors`, ADR-010).

### Fixed
- Titles such as "Undergraduate Research Programme" are now categorised `research_programme` (previously `other`), so that preference actually matches (ADR-014).
- Wheel installs now include the SQL migrations, so `ohg init`/`ohg onboard` work outside an editable checkout.
- Child pages behind an index that returns 304 are now revalidated on their own freshness window (`discovery_policy.child_recheck_hours`) with their own ETag/Last-Modified; fresh children are skipped, the page limit counts every request, and missing/held children are flagged without deleting opportunities (`source_pages`, migration 0007, ADR-011).

## [0.1.0] - 2026-10-30

First public version. Built and tested against fakes, not yet run against the real Telegram API, FreeLLMAPI gateway, Keychain or launchd.

### Added
- **Foundation (M1):** `ohg` CLI, layered config, SQLite with checksummed immutable migrations, `init`, `doctor`, `status`, backups and integrity checks.
- **Sources and fetching (M2):** source YAML schema and import, SSRF-safe fetcher with per-host throttling, conditional GET and size caps, plus RSS/Atom, HTML and sitemap adapters.
- **Candidates and evidence (M3):** deterministic extraction, conservative dedupe, provenance claims, promotion transaction, conflict handling and a review queue.
- **LLM extraction (M4):** optional FreeLLMAPI route with payload redaction, literal-quote grounding and an operator acknowledgement gate. LLM output is always `unverified`.
- **Scoring and alerts (M5):** local profile, eligibility, separate fit and urgency scores, action planner, deadline sentinel and an idempotent Telegram outbox.
- **Operations (M6):** weekly and change reports, `.ics` export, launchd scheduling, backup retention, catch-up after missed runs, source audit and probe.
- Research on 50 candidate sources with evidence and draft configs (`docs/research/`). None are enabled.
- Generated architecture diagram in the README (`scripts/update_architecture.py`).
- MIT license, CI, contributing and security docs.

### Changed
- robots.txt is informational only and no longer gates requests (ADR-008). `crawling.obey_robots_txt` was removed.
- Design docs moved to `docs/design/`.
