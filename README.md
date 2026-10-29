# Opportunity Radar

A single-user, local CLI that discovers, verifies, scores and monitors research/education
opportunities (internships, summer schools, fellowships, CFPs, hackathons) and alerts you on
Telegram. Everything runs on your machine; the only data that can leave it are redacted
**public** page excerpts sent to your local FreeLLMAPI gateway (see below).

Design: `opportunity_radar_hld_v1_2.md`, `opportunity_radar_lld_v1_2.md`; decisions in `docs/adr/`.
Contributor/agent notes: `CLAUDE.md`.

## Principles

- Official sources establish facts. A date is *confirmed* only when a T1/T2 source states it in
  grounded text and deterministic checks pass. LLM output, feeds, aggregators and manual entries
  can never confirm anything.
- A failed fetch is never a fact: it does not clear a deadline or cancel an edition.
- Coverage is reported honestly: `radar report sources` shows real counts, never the ~200 target.

## Setup

```bash
uv sync
uv run radar init                              # creates ~/Library/Application Support/OpportunityRadar
cp config/profile.example.yaml "$HOME/Library/Application Support/OpportunityRadar/profile.yaml"   # edit it
uv run radar doctor
```

Secrets go in the Keychain (launchd jobs do not inherit your shell):

```bash
uv run radar secrets set TELEGRAM_BOT_TOKEN
uv run radar secrets set TELEGRAM_CHAT_ID
uv run radar secrets set RADAR_FREELLMAPI_API_KEY   # only if you use the LLM route
uv run radar notify test
```

LLM (optional): run FreeLLMAPI on 127.0.0.1:3001 with a free-tier-only chain named `radar-free`,
then `uv run radar llm ack` (records that redacted public excerpts may reach upstream providers) and
`uv run radar llm status`. Without it, everything except LLM-proposed fields still works.

## Adding sources (the quality bar matters more than the count)

`config/sources/*.yaml` are empty batch files. For each batch of ~10 real, official sources:
review robots.txt and terms, record them (`robots_policy_checked_at`, `terms_review_note`), set a
`portfolio`, then:

```bash
uv run radar sources probe config/sources/de_research.yaml    # live check, imports nothing
uv run radar sources import config/sources/de_research.yaml
uv run radar sources audit
```

## Running

```bash
uv run radar run all            # catch-up: sentinel, discovery, LLM queue, scoring, alerts
uv run radar run sentinel       # daily: stale marking, re-verify imminent deadlines, reminders
uv run radar run digest         # weekly Telegram digest
uv run radar opportunities list
uv run radar deadlines --within 60d
uv run radar report weekly      # Markdown in <home>/reports
uv run radar export-ics --output ~/radar.ics
```

Schedule it: `scripts/install_launchd.sh` (sentinel daily, discovery + digest weekly, backup daily;
times in the `schedule:` settings). `radar status` lists overdue jobs if the Mac was asleep.
Remove with `scripts/uninstall_launchd.sh`.

## Backups

`radar db backup` (daily via launchd; keeps 7 daily + 4 weekly), `radar db restore --check FILE`,
`radar db restore FILE --to /tmp/test.sqlite3`. The live database is never overwritten.

## Development

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy
```

Tests use fakes for HTTP, DNS, the LLM gateway, Telegram, the Keychain and launchd; none of them
touch the network.
