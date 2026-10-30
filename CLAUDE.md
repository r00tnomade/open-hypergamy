# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

OpenHypergamy is a single-user, local CLI (`ohg`) that discovers, verifies, scores, and monitors research/education opportunities (internships, summer schools, fellowships, CFPs, hackathons) and alerts via Telegram. **Milestones 1–6 are implemented** (see "Implemented so far" below); later milestones are in the execution plan. Design docs:

- `docs/design/open_hypergamy_lld_v1_2.md` — **the implementation contract.** Exact SQL schema (§4), Pydantic contracts and module interfaces (§5), source YAML schema (§6), fetch rules (§7), LLM request/response schema (§9), Telegram templates and idempotency keys (§13), CLI surface and exit codes (§14), test matrix (§18), milestones (§19), task order (§22).
- `docs/design/open_hypergamy_hld_v1_2.md` — rationale, goals/non-goals, trust tiers, risks.

Where the two differ (repo layout, module names, table set), **the LLD wins**. Deviations from the LLD must be recorded as an ADR (`docs/adr/`, ADR-001 lives in LLD §19.1).

Git: this directory is its own repo (the parent home-directory repo is unrelated). Decisions that deviate from or clarify the LLD live in `docs/adr/`.

## Commands

```bash
uv sync                                   # install deps from committed uv.lock
uv run pytest                             # full suite — must pass with no network
uv run pytest tests/unit/test_dates.py::test_missing_year   # single test
uv run pytest tests/security               # one suite (unit|integration|contract|security)
uv run ruff check . && uv run ruff format --check .
uv run mypy                               # strict; files configured in pyproject.toml
OHG_HOME=$(mktemp -d) uv run ohg init # dev runs must never touch ~/Library/Application Support/OpenHypergamy
uv run ohg doctor --strict              # exit 5 if a dependency (LLM gateway) is down
OHG_HOME=$(mktemp -d) uv run ohg onboard  # local onboarding GUI (127.0.0.1 only)
cd frontend && npm ci && npm run build    # typecheck + rebuild GUI into src/open_hypergamy/gui/static (commit it)
cd frontend && npm run e2e                # Playwright against tests/gui_harness.py fakes (no network/Keychain)
```

Gotchas: ruff is configured with `extend-exclude = ["*.md"]` — never remove it, or `ruff format` rewrites the Python snippets inside the design docs. `ohg` locates `migrations/` relative to the source tree, so it needs the editable install from `uv sync`. Tests clear all `OHG_*`/`TELEGRAM_*` env vars and point `OHG_HOME` at a temp dir (`tests/conftest.py`).

## Architecture

Python 3.12+ **modular monolith**, package `src/open_hypergamy/`, Typer + Rich CLI. Data flows one way:

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

1. **The LLM never confirms anything.** Only official-source (T1/T2, field-authority-appropriate) evidence plus deterministic validation can set `confirmed_official`. `ohg review accept` records human acceptance and does **not** set `confirmed_official`.
2. **Quote grounding (LLD §9.5).** Every LLM claim cites a `segment_id` from the exact payload, and its quote must be a literal substring of that segment (whitespace-normalized only). If that fails, reject the claim. Don't search for a near match.
3. **Failure ≠ fact.** A 404, timeout, empty page, or parser failure never clears a deadline, cancels an edition, or counts as a clean empty scan.
4. **Dates.** Keep event dates separate from application/other deadlines. Always store `raw_date_text`. Never assume 23:59, never infer a missing year, and treat a timezone as unknown unless it is stated.
5. **LLM data routing.** The default is FreeLLMAPI at `http://127.0.0.1:3001/v1`, model `auto:ohg-free`, loopback only. Payloads contain only redacted public-source excerpts (≤12,000 chars): never the profile, CV, DB contents, paths, secrets, or Telegram IDs. Never auto-switch to another provider or profile. If the LLM is unavailable, queue the work and keep deterministic processing running. The first LLM use requires a recorded operator acknowledgement.
6. **Crawl safety.** robots.txt is informational only and never gates a request (ADR-008); policy comes from the source config. Keep per-host throttling (3 s), enforce size/redirect/depth caps, and use domain/path allowlists. Block SSRF: reject loopback, private, and link-local targets, including after DNS resolution and on redirect. No login, CAPTCHA, or paywall bypass, and no SERP scraping. Playwright is off unless the source ID is allowlisted.
7. **Idempotency.** Action keys are `action:{edition_id}:{action_type}:{deadline_id|none}:{policy_version}`. Deadline-reminder keys are `deadline:{edition_id}:{deadline_id}:{offset}:{due_date}`. The notification outbox writes a `pending` row *before* sending (at-least-once delivery).
8. **Secrets** come only from env vars or the Keychain. They never go in YAML or SQLite and are redacted from every log and exception.
9. **Honest coverage.** 200 sources is a target. Always report real configured/enabled/healthy counts.

## Execution plan

Build order follows LLD §22. Each milestone ends at an exit gate (LLD §19) before the next one starts. **Build the thin vertical slice first**: one real official source → one edition → one evidence-backed deadline → one action → one Telegram alert. Do this before broadening adapters or seeding sources.

| # | Milestone | Scope (LLD §22 tasks) | Exit gate |
|---|---|---|---|
| M1 | Foundation | 1–2: `pyproject`/`uv.lock`, CLI shell, config loader (defaults → `settings.yaml` → env → flags, Pydantic-validated), `errors.py`, `clock.py`, `OHG_HOME` dir (0700), SQLite factory (FK on, WAL, busy_timeout), `0001_initial.sql` + checksummed runner, `init`/`doctor`/`status`, `db backup`/`integrity-check` | Fresh temp-dir init passes integrity; migrations repeatable and checksum-protected |
| M2 | Sources + fetch | 3–6: source YAML schema + idempotent import, URL canonicalizer + SSRF/policy checks, source repos + `job_runs`, `httpx` fetcher (conditional GET, throttle, retries, caps, body cache), RSS/Atom + HTML adapters, then sitemap | Fixture fetches correct; `304` isn't a change; failures recorded; denied links never fetched |
| M3 | Candidates + evidence | 7–8: fingerprints `title\|organizer_domain\|edition_key`, conservative dedupe (fuzzy → review queue), deterministic extraction, claims, promotion transaction, conflict handling | Every candidate traces to an observation; ambiguous dates can't auto-confirm |
| M4 | LLM | 9: httpx OpenAI-compatible client (FreeLLMAPI + manual local adapters), payload redaction/budget, Pydantic `opportunity_extract.v1`, grounding validator, `llm_cache`, acknowledgement gate, review CLI | LLM disabled ⇒ scanning still works; ungrounded output can't set verification state |
| M5 | Rank + alert | 10–12: `config/profile.yaml` (gitignored), eligibility, fit (weights 30/25/20/15/10) + separate urgency, score snapshots w/ reason codes, action planner, sentinel (30/14/7/2 d), Telegram outbox + retry | Re-runs create no duplicate alerts; alerts carry official link + certainty label |
| M6 | Ops + sources | 13–14: weekly report, `.ics` (estimates excluded by default), launchd install/uninstall (absolute paths), backup retention, catch-up logic (LLD §15.2), seed sources in reviewed batches | Real counts and monitoring gaps visible |

Testing is built alongside each milestone, not after: unit tests plus HTTP/LLM/Telegram fakes and saved public-page fixtures under `tests/fixtures/`. Nothing may hit the live network. Live smoke tests are opt-in.

## Implemented so far (M1–M6)

All six milestones are implemented; what remains is operational: seed and audit real sources in reviewed batches, run against the real LLM/Telegram/launchd, and the not-built adapters. Decisions are in `docs/adr/` (ADR-002 config/doc fixes, 003 fetch, 008 robots.txt informational, 010 selectors, 004 candidates/evidence, 005 LLM, 006 scoring/alerts, 007 operations, 009 source health/fetch resilience, 011 child-page revalidation, 012 egress proxies, 013 authorized access resilience). Read ADR-004–007 before changing verification, promotion, the LLM path, scoring, alerts or scheduling.

- **Config/DB (M1):** `config.py` (precedence defaults → YAML → env → CLI; unknown keys warn; sets the local timezone), `persistence/db.py`, `persistence/migrations.py` (DB checksum + `migration_manifest.json`). **After adding a migration run `python3 scripts/update_manifest.py`.** Applied migrations are immutable (head: 0008).
- **Sources (M2):** `sources/urls.py` (SSRF), `policy.py`, `fetch.py` (`HostGate`: per-host slots + adaptive delay, 3 s floor), `barriers.py` (200 challenge/login detection), `pages.py` + `source_pages` table (child pages revalidated on their own window even when the index is 304, ADR-011; failures mark pages missing/held, never delete), `health.py` (derived health state + circuit breaker, ADR-009; holds end only via `ohg sources unblock`), adapters `html`/`rss_atom`/`sitemap`, `registry.py` (YAML schema, portfolios), `discovery/orchestrator.py`.
- **Candidates/evidence (M3):** `extraction/dates.py` + `deterministic.py`, `discovery/{candidates,pipeline,promotion,review}.py`, `verification/{evidence,rules,chronology}.py` (`verify_fact` is **the only code that may return `confirmed_official`**).
- **LLM (M4):** `llm/` + `extraction/llm_extractor.py`; LLM facts are `extraction_method='llm'`, always `unverified`.
- **Scoring/alerts (M5):** `profile.py`, `verification/eligibility.py`, `scoring/`, `monitoring/{deadlines,recheck,cycle}.py`, `notifications/`.
- **Operations (M6):** `reporting/{weekly,changes,sources,calendar}.py`, `scheduling/launchd.py`, `keychain.py`, `monitoring/catchup.py`, `observability/jobs.py` (`tracked_job`), `persistence/backups.py`, `cli_ops.py` (registered by `cli.py`; shared option aliases live in `cli_common.py`).
- **Egress proxies (ADR-012):** `egress/` + `cli_proxy.py`; off by default, direct by default, operator-trusted profiles only, failover for proxy-infrastructure faults only (never after 401/403/429/451/challenge), no direct fallback for assigned sources, HostGate stays keyed by destination. Fetches made for a source must run inside `egress_scope(source_key)`. All httpx clients use `trust_env=False`. Head migration: 0008.
- **Onboarding GUI (ADR-014):** `ohg onboard` (`cli_gui.py`) → `gui/server.py` (stdlib, loopback) → `gui/app.py` (session/CSRF/Origin/Host, CSP) → `gui/service.py` (orchestration only; reuses `persistence/bootstrap.py`, `profile.save_profile`, `settings_store`, `keychain`, `notifications/telegram.check_bot|recent_chats`, LLM client/ack, scoring). Frontend source in `frontend/` (Preact + TS + Vite); the build output in `gui/static/` is committed. The GUI writes settings only to `<home>/settings.yaml` (allowlisted keys, ranks below hand-written files) and never returns secrets. Progress/drafts: `<home>/onboarding.json`. Scoring is `score-v2` (`preferences.categories`, `WORLDWIDE`). Wheels ship migrations as `open_hypergamy/_migrations`.
- **Access resilience (ADR-013):** `resilience/` + `cli_resilience.py` (`sources alternatives|permission-request`, `import newsletter`, `measure recall`); adapters `ical`/`json_feed`; `RenderingRequired` holds JS-shell sources (no rendering built); simulated publishers in `tests/simulation/`. The 97 % recall target is unmeasured and must not be claimed without an attested ground-truth set.
- **Time:** date-only deadline arithmetic uses `clock.local_today(now)` (configured `app.timezone`), never `now.date()` on a UTC datetime.
- **CLI:** see `ohg --help`; groups: `sources` (incl. `audit`, `probe`), `run` (`discovery|llm|score|sentinel|digest|all`), `candidates`, `review`, `opportunities`, `actions`, `deadlines`, `report`, `export-ics`, `profile`, `llm`, `notify`, `launchd`, `secrets`, `db`. `db restore` never overwrites the live DB.
- **Test doubles:** `tests/helpers.py` (`FakeWeb`, `make_fetcher`), `helpers_llm.py` (`FakeGateway`, `ev()`), `helpers_tg.py` (`FakeBotApi`, `RecordingSink`). `tests/conftest.py` disables the Keychain and send delays. Tests must never reach the network, sleep, or the real Keychain/launchd. Drive time with a `FixedClock` subclass; CLI tests use the system clock, so build dated fixtures relative to `local_today(datetime.now(UTC))`. SQL without `ORDER BY` has no stable order (a flaky test came from this).
- **Lint config:** ruff ignores `*.md` (never remove it) and E501 for SQL/message-heavy modules (see `pyproject.toml`).
- **Not done:** Playwright adapter (such sources are `skipped`); no real source URLs are seeded (`config/sources/*.yaml` are empty on purpose); LLM, Telegram, Keychain and launchd have never run against the real services/OS facilities.
