# Contributing

Gatekeeping opportunities is a poverty mindset, so contributions are welcome: sources, fixes, better extraction rules, sharper tests.

## Setup

```bash
uv sync
OHG_HOME=$(mktemp -d) uv run ohg init   # never develop against your real data directory
```

## Before you open a PR

All four must pass. CI runs the same commands on Linux and macOS:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

- **Tests never touch the network**, the real Keychain, Telegram or launchd. Use the fakes in `tests/helpers*.py`.
- **Migrations are immutable** once applied. A schema change is a new `migrations/NNNN_*.sql` file plus `python3 scripts/update_manifest.py`.
- **The LLD is the contract** (`docs/design/open_hypergamy_lld_v1_2.md`). If your change deviates from it, record the decision as an ADR in `docs/adr/`.
- **The invariants in `CLAUDE.md` are not negotiable.** The big ones: the LLM never confirms a fact, a failed fetch is never a fact, and dates are never guessed.
- If you change module dependencies, refresh the README diagram: `graphify update src && python3 scripts/update_architecture.py` (`--check` tells you whether it is stale).

## Adding sources

Quality over count. A source entry needs a real terms review written into `terms_review_note`, plus `robots_policy_checked_at`. Probe it with `ohg sources probe FILE` before proposing it. Don't submit sources that require logins, sit behind bot challenges, or whose terms prohibit automated access. Nothing gets enabled without a review.

## Style

Match the surrounding code. Keep comments for the *why*. Commit messages follow `type(scope): summary` (`feat`, `fix`, `docs`, `chore`, `test`).
