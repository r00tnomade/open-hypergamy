# Changelog

All notable changes are listed here. The project is pre-1.0, so anything may still change.

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
