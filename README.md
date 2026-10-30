# OpenHypergamy

**Career hypergamy. Open source.**

*LARP never stops. Professionally.*

Stop finding out about the good stuff after the deadline.

OpenHypergamy watches the places where good opportunities actually get announced (research labs, fellowships, summer schools, hackathons, calls for papers), checks the facts against the official page, scores what's worth your time, and pings you on Telegram before the window closes. It runs on your laptop. Your profile never leaves it.

> Short name: the command is `ohg`, the package is `open_hypergamy`.

Design docs: `open_hypergamy_hld_v1_2.md` and `open_hypergamy_lld_v1_2.md`. Decisions: `docs/adr/`. Contributor and agent notes: `CLAUDE.md`.

## The rules of the game

1. **Official page or it didn't happen.** A date is *confirmed* only when an official source says it in text we can quote back, and the checks pass. Feeds, aggregators, manual entries and the LLM can all tell you where to look. None of them can confirm anything.
2. **A broken fetch is not news.** A 404 doesn't cancel a programme. A timeout doesn't erase a deadline. The last known fact stays, and it gets marked stale until someone re-checks it.
3. **Estimated stays estimated.** If a date isn't confirmed, you'll see that label everywhere: alerts, reports, calendar. No joke is worth a wrong deadline.
4. **Honest coverage.** The goal is about 200 curated sources. `ohg report sources` tells you how many you actually have, how many are healthy, and what's missing. It never rounds up.
5. **No guarantees.** This finds the doors. It doesn't get you through them.

## Setup

```bash
uv sync
uv run ohg init        # creates ~/Library/Application Support/OpenHypergamy
uv run ohg doctor      # tells you what's missing
```

Write your profile (degree level, year, interests; stays local, never goes to the LLM or Telegram):

```bash
cp config/profile.example.yaml "$HOME/Library/Application Support/OpenHypergamy/profile.yaml"
```

Telegram, so the pipeline can yell at you. Tokens go in the macOS Keychain, because scheduled jobs don't inherit your shell:

```bash
uv run ohg secrets set TELEGRAM_BOT_TOKEN
uv run ohg secrets set TELEGRAM_CHAT_ID
uv run ohg notify test
```

Optional LLM route, for the messy prose (eligibility wording, funding details): run [FreeLLMAPI](https://github.com/tashfeenahmed/freellmapi) on `127.0.0.1:3001` with a free-tier-only chain called `ohg-free`, then:

```bash
uv run ohg secrets set OHG_FREELLMAPI_API_KEY
uv run ohg llm ack     # you confirm: redacted public excerpts may reach upstream providers
uv run ohg llm status
```

Skip it and everything still works. You just lose the LLM-proposed extras, which were only ever suggestions anyway.

## Find the sauce (adding sources)

The `config/sources/*.yaml` batch files are **empty on purpose**. Nobody verified real URLs, robots rules or site terms on your behalf, and filling the quota with junk defeats the point. Quality over count.

For each batch of ~10 official sources: read the site's terms (robots.txt is shown for information only, see ADR-008), write them down in the entry (`robots_policy_checked_at`, `terms_review_note`), pick a `portfolio`, then:

```bash
uv run ohg sources probe  config/sources/de_research.yaml   # live check, imports nothing
uv run ohg sources import config/sources/de_research.yaml
uv run ohg sources audit                                    # what's still weak?
```

Sources without a recorded policy review get imported disabled. That's a feature.

## Run the pipeline

```bash
uv run ohg run all          # catch-up: sentinel, discovery, LLM queue, scoring, alerts
uv run ohg run sentinel     # daily: re-verify imminent deadlines, fire reminders
uv run ohg run digest       # weekly Telegram digest
```

What you get out:

```bash
uv run ohg opportunities list           # ranked, with fit, urgency, eligibility
uv run ohg opportunities show <id> --evidence   # the quote and link behind every fact
uv run ohg deadlines --within 60d
uv run ohg actions list                 # what to actually do next
uv run ohg report weekly                # Markdown, links included
uv run ohg export-ics --output ~/ohg.ics
```

Reminders land at 30, 14, 7 and 2 days, for confirmed deadlines on things worth your time. If your laptop slept through a week, you get the most urgent reminder and a note that monitoring had a gap, not a pile of stale pings.

When you decide something yourself, tell it: `ohg opportunities set-action <id> applied`. The planner leaves that alone until you hand it back with `auto`.

### Put it on a schedule

```bash
scripts/install_launchd.sh      # sentinel + backup daily, discovery + digest weekly
scripts/uninstall_launchd.sh
```

`ohg status` lists anything overdue, so a sleeping Mac doesn't fail silently.

## Backups

`ohg db backup` runs daily (keeps 7 daily + 4 weekly). Check one with `ohg db restore --check FILE`, or restore into a throwaway file with `ohg db restore FILE --to /tmp/test.sqlite3`. Your live database is never overwritten.

## Security and responsible use

OpenHypergamy is a tool for discovering, monitoring and researching publicly announced opportunities. It reads pages you point it at, at modest rates, from your own machine.

**Your responsibility.** You decide which sources to configure and how to use what they return. Make sure your use complies with applicable law, any contracts you have agreed to, and the rights of third parties. Public accessibility alone does not give you permission to reproduce, redistribute or commercially exploit content. Copyright, database rights, privacy law and each site's terms of service apply independently of one another and of anything this software does or does not check.

**robots.txt.** OpenHypergamy does not enforce robots.txt. It may retrieve the file and show what it says, but source policy is yours to set in the source configuration, and a missing objection in robots.txt is not permission. Read the terms of every source before enabling it, and record that review in the entry.

**What the software will not do.** It is not designed to bypass authentication, paywalls, CAPTCHAs, IP blocks or other technical access controls, and it must not be used or modified for that purpose. A `403` or similar response is treated as a stop-and-review signal, and `429` and `Retry-After` are honoured.

**Be a good neighbour.** Keep request rates low, leave the per-host throttle in place, prefer feeds and published APIs, and do not put load on services that are not yours. If a site owner asks you to stop, stop.

**No warranty.** The software is provided "AS IS", without warranty of any kind, to the extent permitted by applicable law. The maintainers do not authorize unlawful use and accept no responsibility for how it is used.

*This notice is not legal advice. It does not establish that any particular crawling or reuse activity is lawful. If you are unsure, ask a qualified lawyer or the site's operator.*

## Share the sauce

Gatekeeping opportunities is a poverty mindset. Sources, fixes and better extraction rules are all welcome. The one rule: don't trade factual clarity for a punchline, and don't let anything but an official source confirm a deadline.

## Development

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy
```

Tests fake the network, DNS, the LLM gateway, Telegram, the Keychain and launchd. None of them touch the real ones.

## Status

Built and tested end to end against fakes. Not yet run against the real FreeLLMAPI gateway, the real Telegram API, a live Keychain or an actual launchd. Run `ohg doctor`, then `ohg notify test`, before you trust it with a deadline. Touch grass occasionally.
