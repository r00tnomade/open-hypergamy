# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Opportunity Radar is a single-user, local CLI (`radar`) that discovers, verifies, scores, and monitors research/education opportunities (internships, summer schools, fellowships, CFPs, hackathons) and alerts via Telegram. **Milestone 1 (foundation) is implemented**: config, errors, clock, SQLite + checksummed migrations, `radar init|doctor|status|db …`. Milestones 2–6 are not started. Design docs:

- `opportunity_radar_lld_v1_2.md` — **the implementation contract.** Exact SQL schema (§4), Pydantic contracts and module interfaces (§5), source YAML schema (§6), fetch rules (§7), LLM request/response schema (§9), Telegram templates and idempotency keys (§13), CLI surface and exit codes (§14), test matrix (§18), milestones (§19), task order (§22).
- `opportunity_radar_hld_v1_2.md` — rationale, goals/non-goals, trust tiers, risks.

Where the two differ (repo layout, module names, table set), **the LLD wins**. Deviations from the LLD must be recorded as an ADR (`docs/adr/`, ADR-001 lives in LLD §19.1).

Git: this directory is its own repo (`git init` was run here; the parent home-directory repo is unrelated). No commits yet. Resolutions of LLD inconsistencies are in `docs/adr/ADR-002-m1-config-and-doc-resolutions.md`.

## Commands

```bash
uv sync                                   # install deps from committed uv.lock
uv run pytest                             # full suite — must pass with no network
uv run pytest tests/unit/test_dates.py::test_missing_year   # single test
uv run pytest tests/security               # one suite (unit|integration|contract|security)
uv run ruff check . && uv run ruff format --check .
uv run mypy                               # strict; files configured in pyproject.toml
RADAR_HOME=$(mktemp -d) uv run radar init # dev runs must never touch ~/Library/Application Support/OpportunityRadar
uv run radar doctor --strict              # exit 5 if a dependency (LLM gateway) is down
```

Gotchas: ruff is configured with `extend-exclude = ["*.md"]` — never remove it, or `ruff format` rewrites the Python snippets inside the design docs. `radar` locates `migrations/` relative to the source tree, so it needs the editable install from `uv sync`. Tests clear all `RADAR_*`/`TELEGRAM_*` env vars and point `RADAR_HOME` at a temp dir (`tests/conftest.py`).

## Architecture

Python 3.12+ **modular monolith**, package `src/opportunity_radar/`, Typer + Rich CLI. Data flows one way:

```
sources/ (adapters → PageObservation) → discovery/ (canonicalize, dedupe → candidates)
  → extraction/ (deterministic first, then llm_extractor) → verification/ (grounding, rules, eligibility)
  → persistence/ (promotion transaction) → scoring/ (fit, urgency, actions)
  → monitoring/ (deadline sentinel, source health) → notifications/ (Telegram outbox) / reporting/ (Markdown, .ics)
```

Layering rules (LLD §5.2):
- Adapters return `PageObservation` or a typed failure. They never write programme/edition tables, call Telegram, or touch scoring.
- Repositories own SQL transactions; services own orchestration/policy. DB models don't leak into scraper code.
- **Never hold a write transaction across network I/O or LLM calls.**
- Time comes from the injected `Clock` (`clock.py`); app code sets `created_at`/`updated_at`, never SQLite defaults.
- Per-source errors are caught, recorded in `source_check_runs`/`job_runs`, and the job ends `partial` with exit code 4. Only unsafe DB state or invalid config aborts a run.

Data model essentials (LLD §4):
- `programs` (stable identity) → `editions` (one cycle, `UNIQUE(program_id, edition_key)`) → `deadlines` (one row per milestone type). One year's facts never overwrite another's.
- `claims` is the append-oriented provenance log (exactly one of program/edition/deadline FK). Edition/deadline rows hold only the *materialized current* state.
- Migrations live in `migrations/NNNN_*.sql`, are immutable once applied, and are checksum-verified. A mismatch is fatal. Schema changes always mean a new file.
- Enums are persisted as lowercase snake_case strings (`StrEnum`), never ordinals. JSON columns are serialized with `sort_keys=True` and compact separators.

## Invariants that must not be broken

These cut across modules and are the core of the design. Tests in `tests/security` and `tests/contract` should enforce them.

1. **The LLM never confirms anything.** Only official-source (T1/T2, field-authority-appropriate) evidence plus deterministic validation can set `confirmed_official`. `radar review accept` records human acceptance and does **not** set `confirmed_official`.
2. **Quote grounding (LLD §9.5).** Every LLM claim cites a `segment_id` from the exact payload, and its quote must be a literal substring of that segment (whitespace-normalized only). If that fails, reject the claim. Don't search for a near match.
3. **Failure ≠ fact.** A 404, timeout, empty page, or parser failure never clears a deadline, cancels an edition, or counts as a clean empty scan.
4. **Dates.** Keep event dates separate from application/other deadlines. Always store `raw_date_text`. Never assume 23:59, never infer a missing year, and treat a timezone as unknown unless it is stated.
5. **LLM data routing.** The default is FreeLLMAPI at `http://127.0.0.1:3001/v1`, model `auto:radar-free`, loopback only. Payloads contain only redacted public-source excerpts (≤12,000 chars): never the profile, CV, DB contents, paths, secrets, or Telegram IDs. Never auto-switch to another provider or profile. If the LLM is unavailable, queue the work and keep deterministic processing running. The first LLM use requires a recorded operator acknowledgement.
6. **Crawl safety.** Follow robots and per-host throttling (3 s), enforce size/redirect/depth caps, and use domain/path allowlists. Block SSRF: reject loopback, private, and link-local targets, including after DNS resolution and on redirect. No login, CAPTCHA, or paywall bypass, and no SERP scraping. Playwright is off unless the source ID is allowlisted.
7. **Idempotency.** Action keys are `action:{edition_id}:{action_type}:{deadline_id|none}:{policy_version}`. Deadline-reminder keys are `deadline:{edition_id}:{deadline_id}:{offset}:{due_date}`. The notification outbox writes a `pending` row *before* sending (at-least-once delivery).
8. **Secrets** come only from env vars or the Keychain. They never go in YAML or SQLite and are redacted from every log and exception.
9. **Honest coverage.** 200 sources is a target. Always report real configured/enabled/healthy counts.

## Execution plan

Build order follows LLD §22. Each milestone ends at an exit gate (LLD §19) before the next one starts. **Build the thin vertical slice first**: one real official source → one edition → one evidence-backed deadline → one action → one Telegram alert. Do this before broadening adapters or seeding sources.

| # | Milestone | Scope (LLD §22 tasks) | Exit gate |
|---|---|---|---|
| M1 | Foundation | 1–2: `pyproject`/`uv.lock`, CLI shell, config loader (defaults → `settings.yaml` → env → flags, Pydantic-validated), `errors.py`, `clock.py`, `RADAR_HOME` dir (0700), SQLite factory (FK on, WAL, busy_timeout), `0001_initial.sql` + checksummed runner, `init`/`doctor`/`status`, `db backup`/`integrity-check` | Fresh temp-dir init passes integrity; migrations repeatable and checksum-protected |
| M2 | Sources + fetch | 3–6: source YAML schema + idempotent import, URL canonicalizer + SSRF/policy checks, source repos + `job_runs`, `httpx` fetcher (conditional GET, throttle, retries, caps, body cache), RSS/Atom + HTML adapters, then sitemap | Fixture fetches correct; `304` isn't a change; failures recorded; denied links never fetched |
| M3 | Candidates + evidence | 7–8: fingerprints `title\|organizer_domain\|edition_key`, conservative dedupe (fuzzy → review queue), deterministic extraction, claims, promotion transaction, conflict handling | Every candidate traces to an observation; ambiguous dates can't auto-confirm |
| M4 | LLM | 9: httpx OpenAI-compatible client (FreeLLMAPI + manual local adapters), payload redaction/budget, Pydantic `opportunity_extract.v1`, grounding validator, `llm_cache`, acknowledgement gate, review CLI | LLM disabled ⇒ scanning still works; ungrounded output can't set verification state |
| M5 | Rank + alert | 10–12: `config/profile.yaml` (gitignored), eligibility, fit (weights 30/25/20/15/10) + separate urgency, score snapshots w/ reason codes, action planner, sentinel (30/14/7/2 d), Telegram outbox + retry | Re-runs create no duplicate alerts; alerts carry official link + certainty label |
| M6 | Ops + sources | 13–14: weekly report, `.ics` (estimates excluded by default), launchd install/uninstall (absolute paths), backup retention, catch-up logic (LLD §15.2), seed sources in reviewed batches | Real counts and monitoring gaps visible |

Testing is built alongside each milestone, not after: unit tests plus HTTP/LLM/Telegram fakes and saved public-page fixtures under `tests/fixtures/`. Nothing may hit the live network. Live smoke tests are opt-in.

## Implemented so far (M1)

`config.py` (Pydantic settings, precedence defaults → YAML → env → CLI, unknown keys warn), `persistence/db.py` (FK on, WAL, `transaction()` = `BEGIN IMMEDIATE`, backup API), `persistence/migrations.py` (contiguous versions, DB checksum + `migration_manifest.json` check; **after editing/adding a migration, update the manifest**), `observability/health.py` (doctor/status), `cli.py`. `db restore` supports only `--check`; backup retention and launchd come in M6.
