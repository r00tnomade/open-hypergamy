# ADR-014: Local GUI onboarding (`ohg onboard`)

Status: accepted. Adds `gui/`, `cli_gui.py`, `settings_store.py`, `persistence/bootstrap.py` and `frontend/`. No migration. Invariants 1–9 in CLAUDE.md are unchanged.

## Context

Setup was CLI-only: copy `profile.example.yaml`, edit YAML, `ohg secrets set`, `ohg notify test`, `ohg llm ack`. That works for operators but not as a first-run experience. The goal is a GUI a new user can finish in about three minutes, without CLI profile commands, that reuses the existing services instead of re-implementing them, and that keeps every local-first and secret-handling guarantee.

## Decision

### Architecture

```
browser ──(loopback HTTP, session cookie + CSRF)──▶ gui/server.py (stdlib ThreadingHTTPServer, 127.0.0.1 only)
                                                      └─▶ gui/app.py      routing, Host/Origin/CSRF/session checks, JSON, CSP
                                                            └─▶ gui/service.py  orchestration only; returns JSON-able dicts
                                                                  ├─ persistence/bootstrap.py   (same init as `ohg init`)
                                                                  ├─ profile.save_profile       (Pydantic Profile → YAML)
                                                                  ├─ settings_store.update      (allowlisted keys → <home>/settings.yaml)
                                                                  ├─ keychain.set_secret/source_of
                                                                  ├─ notifications.telegram     (check_bot/recent_chats/TelegramSink)
                                                                  ├─ llm client/ack             (healthy, list_models, require_ack)
                                                                  └─ scoring + eligibility      (matching preview on fictional examples)
```

- **No new runtime dependency.** The server is `http.server`; `GuiApp.handle(Request) -> Response` is transport-independent and is what the tests drive.
- **Frontend:** Preact + TypeScript + Vite in `frontend/` (dev-only). `npm run build` writes into `src/open_hypergamy/gui/static/`, which is committed so a plain `uv sync` or wheel install has the GUI without Node. Fonts are bundled (`@fontsource`); there are no third-party requests, so the GUI works offline.
- **The frontend never touches SQLite, files or the Keychain.** It only calls the JSON API.
- `ohg init` now calls `bootstrap.initialize` (same behaviour and output) and prints a hint to run `ohg onboard` when no profile exists.

### Deviations from the LLD

1. **App-managed settings file.** `load_config` now also looks for `<home>/settings.yaml`, *after* `--config`/`OHG_CONFIG` and `./config/settings.yaml`. The GUI writes only there, only allowlisted keys (`settings_store.WRITABLE`: timezone, `llm.enabled`, Telegram delivery preferences, digest day/time), and validates the merged result before an atomic 0600 write. When a hand-written file outranks it, the GUI reports settings as managed elsewhere and refuses to write; it never rewrites a user's file. Env vars still override everything.
2. **Profile schema additions (all optional, `version: 1` unchanged):** `display_name`, `academic.institution` (display only, never used for eligibility), and `preferences.categories` (programme categories; empty = "show me everything relevant"). Existing profiles stay valid. The GUI saves through `profile.save_profile` (atomic, 0600, previous file kept as `profile.yaml.bak`); `profile_version` is bumped to `gui-<timestamp>` only when the content changes.
3. **Scoring `score-v2`.** `technical_value` adds +15 for a preferred category and −30 for a non-preferred one (no change when `categories` is empty). `region_ok` treats `WORLDWIDE` as "anywhere". The keyword table gains entries for the GUI's interest catalogue. The version bump makes the change visible in `score_snapshots`. Profiles without categories score as before, but each edition gets one new snapshot row with the new version. Action keys use `ACTION_POLICY_VERSION`, which is unchanged, so no duplicate actions or alerts.
4. **Packaging:** the wheel force-includes `migrations/` as `open_hypergamy/_migrations`, and `DEFAULT_MIGRATIONS_DIR` falls back to it when there is no source tree. Before this, only editable installs could initialise a database.

### Onboarding state

`<home>/onboarding.json` (0600) holds step status (`done`/`skipped`), the current step, and per-step drafts of non-secret fields (filtered against `state.DRAFT_FIELDS`, size-capped). Drafts are autosaved (debounced PUT), so an interrupted session resumes on any browser. A corrupt file is treated as fresh, never as fatal. An install that already has a valid profile but no state file is adopted: profile and preferences are marked done and the forms are prefilled.

### Security controls

| Threat | Control |
|---|---|
| LAN exposure | Bind `127.0.0.1` only; no host option exists |
| Other local web pages / CSRF | Session cookie `HttpOnly; SameSite=Strict`; writes need `X-OHG-CSRF` (per-session, held in memory by the page), an `Origin` equal to the loopback origin, and `Content-Type: application/json` |
| DNS rebinding | `Host` must be exactly `127.0.0.1:<port>` or `localhost:<port>` (else 421) |
| Token in URL/history | Browser opened at `/launch?code=…`: 256-bit, single-use, expires in 5 minutes, redeemed for the cookie then 303 to `/`. Access logs are disabled. Sessions expire after 12 h |
| XSS / injection | CSP `default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'`, no inline script, `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, COOP/CORP |
| Secret disclosure | Tokens/keys are accepted only on dedicated endpoints, written with `keychain.set_secret`, cleared from the input, and **never returned**: responses carry only `environment`/`keychain`/`unset`. Not in drafts, YAML, SQLite, logs or URLs. Telegram error text is scrubbed of the token; all API errors pass through `redact`. Chat ids stay server-side (the page gets opaque single-use refs) |
| Keychain unavailable | The GUI refuses to store secrets and tells the user to use env vars; there is no plaintext fallback |
| Path / internals leakage | Static serving rejects traversal; 500s return a generic message; the read model contains no filesystem paths |
| Unintended sends | Token check uses `getMe`, chat discovery uses `getUpdates`; `sendMessage` happens only on the explicit "Send test message". Skipping notifications sets `telegram.enabled: false` |
| LLM data | Status uses `/models` only. The optional test is one fixed, non-personal request and requires the recorded acknowledgement (`require_ack`), which the GUI records only after an explicit checkbox and button |

Residual: plain HTTP on loopback, so other processes of the same user could sniff loopback traffic or read the cookie from the browser profile. That is the same trust boundary as the Keychain itself.

### Honesty rules in the UI

- The matching preview runs the real `assess`, `compute_fit`, `compute_urgency`, `priority_band` and `recommended_action` on three clearly labelled fictional examples, and shows the *recommended action*, not a raw band. "Certainty" is a plain summary of what the rules could settle, not a probability.
- AI status shows gateway reachability, whether the configured model route is listed, key presence and acknowledgement. The GUI cannot create the `ohg-free` chain and says so, with manual steps.
- The dashboard shows real configured, enabled and healthy source counts against the 200 target. Onboarding never enables a source.

## Consequences

- Rebuild the frontend (`cd frontend && npm ci && npm run build`) after UI changes and commit `src/open_hypergamy/gui/static/`.
- Browser tests (`npm run e2e`) run the real server against fakes (`tests/gui_harness.py`), never real Telegram, Keychain or LLM.
- Schedule times changed in the GUI apply to launchd after `ohg launchd install` is re-run; the GUI says so and does not install agents itself.
- Bundled third-party licences (SIL OFL 1.1 for both fonts, MIT for Preact) are copied by `npm run build` (`frontend/scripts/copy-licenses.mjs`) into `gui/static/licenses/` and ship in the wheel.
- The "21st" component registry was not used: no `API_KEY_21ST` was configured. Components were built in-house following the design system in `design-system/openhypergamy/MASTER.md`.

## Pre-commit review (2026-10-30)

### score-v2 transition

- **One row per edition, once.** `rescore_edition` writes a snapshot only when `(scoring_version, profile_version, scores, band, reasons, eligibility, distance)` differs from the latest row. The first run after the upgrade writes exactly one `score-v2` row per edition; later runs and restarts write none (`tests/integration/test_score_v2_transition.py`).
- **History kept.** `score_snapshots` is append-only; `score-v1` rows are never updated or deleted. With no category preference the v2 fit is numerically identical to v1.
- **No duplicate notifications or actions.** Alert keys (`new:{edition}`, `opened:{edition}:{date}`, `deadline:{edition}:{deadline}:{offset}:{date}`) and action keys (`…:actions-1`) don't contain the scoring version. A preference change can *legitimately* produce a first `new:` alert for an edition that only now crosses `minimum_fit_score_for_immediate_alert`; that is a new alert, not a duplicate.
- **Profile version.** The GUI bumps `profile_version` only when the content changes, and two edits within the same second get distinct versions (`gui-<ts>.2`). Each bump adds one eligibility-assessment row and one snapshot per edition.
- **Category coverage fix.** `discovery/normalize.guess_category` never produced `research_programme`, so the GUI's "Research programmes" choice matched nothing. A rule for `research programme|undergraduate research|summer research` now runs **after** all existing rules, so only titles that used to fall through to `other` change. It applies to programmes created from now on; stored categories aren't rewritten. Those programmes get the pre-existing `research_programme` base value (85 instead of 40 for `other`).

### Security residuals (accepted for a single-user loopback tool)

- **Cookies aren't port-scoped.** The browser also sends `ohg_session` to other services on `127.0.0.1`/`localhost`, any port, while the session lives (12 h, in memory only, gone when `ohg onboard` stops). A malicious service listening on loopback could capture it. A same-user attacker can read the profile files directly anyway, so the exposure is to *other* local users' services. Mitigations if needed: shorter TTL, idle shutdown.
- **No rate limiting.** Launch codes are 256-bit, single-use and expire in 5 minutes; session tokens are 256-bit. Online guessing is infeasible. A lockout after failed attempts would only give other local processes a way to lock the user out.
- **Launch URL in argv.** `webbrowser.open` passes the one-time URL to the OS opener, briefly visible in the process list. It is single-use, so a reader would have to beat the browser to it.
- **Plain HTTP, no `Secure` flag.** Same trust boundary as the Keychain and profile files.
- **Keychain writes** go through `/usr/bin/security` argv (pre-existing, documented in `keychain.py`).

## Scope: local onboarding is not a remote backend

This ADR covers only a **local, single-user, loopback** setup UI. It is not a foundation for a hosted or remote ("GitHub-first") backend. No such architecture is defined in this repository yet, and it needs its own ADR. Key differences:

| Concern | Local onboarding (this ADR) | Any remote backend (not designed here) |
|---|---|---|
| Users | One operator, the OS account owner | Multiple identities; needs real authN/authZ |
| Auth | One-time launch code → in-memory loopback session | Must not reuse launch codes or loopback Host/Origin checks |
| Transport | Plain HTTP on 127.0.0.1 | TLS, Secure cookies, CORS policy |
| Secrets | macOS Keychain or env vars on the user's machine | A server-side secret store; Keychain semantics don't apply |
| Profile | YAML in `OHG_HOME`; never leaves the machine (invariant 5) | Would conflict with invariant 5; needs an explicit privacy decision first |
| State | Files plus SQLite, single writer | Concurrency, tenancy, migrations under load |
| LLM routing | Loopback FreeLLMAPI only (invariant 5) | Not compatible as-is |

What can carry over: the JSON API *shapes*, the `OnboardingService` boundary (UI → service → existing modules) and the frontend components. What must not: `gui/security.py` session handling, the Keychain-backed secret endpoints, and the assumption that the server and the data share one machine.
