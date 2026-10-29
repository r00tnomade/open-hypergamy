# ADR-002 — Milestone 1 resolutions of LLD inconsistencies

**Status:** Accepted · **Date:** 2026-10-29

## Decisions

1. **Playwright settings key.** LLD §2.1 nests them under `types:`; implemented as `browser:` (`enable_playwright`, `playwright_allowed_source_ids`).
2. **Single source of truth for LLM endpoint/model.** Provider-specific values live only in `llm.freellmapi.*` and `llm.local.*`. The top-level `llm.base_url`/`llm.model` are dropped. `RADAR_LLM_BASE_URL`/`RADAR_LLM_MODEL` apply to the block of the active provider.
3. **Environment names.** The LLD names (`RADAR_LLM_*`, `RADAR_FREELLMAPI_*`) win over the HLD's `LLM_*`.
4. **Database path.** `database.path` defaults to `<RADAR_HOME>/opportunity_radar.sqlite3` instead of a hard-coded macOS path, so `RADAR_HOME` redirects everything (tests, dev runs).
5. **Loopback enforced in config.** Any non-loopback LLM `base_url` fails validation (LLD §17). Login/CAPTCHA/paywall circumvention flags fail validation if true.
6. **Migrations stay in repo-level `migrations/`** (LLD §1.3) and are located relative to the package, so the CLI requires an editable install (`uv sync`). Each file is checked against its DB checksum and `migration_manifest.json`.
7. **LM Studio port.** Default `:3000` kept as in the LLD but flagged; LM Studio's own default is usually `:1234`. Override via `RADAR_LLM_BASE_URL` with `RADAR_LLM_PROVIDER=local`.
8. **`doctor` reachability** is a TCP connect only (no inference request, no HTTP dependency yet).
9. **Python pin** is 3.14 (`.python-version`; installed locally); `requires-python >=3.12`.
