"""First-use acknowledgement of external processing (LLD §9.2)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from open_hypergamy.clock import Clock, iso_z
from open_hypergamy.errors import LLMUnavailable

POLICY_VERSION = "2026-10-29.1"

CHECKLIST = """\
External-processing and zero-cost checklist (LLM route: FreeLLMAPI)
  1. FreeLLMAPI runs locally but may forward redacted PUBLIC page excerpts to upstream providers.
     Inference is not local-only. Your profile, CV, database content, paths, secrets and
     Telegram identifiers are never sent.
  2. Configure a gateway chain named `ohg-free` containing ONLY genuinely free-tier routes.
     Do not add billing-enabled provider credentials, paid routes, or the Premium catalog.
  3. Bind the gateway to 127.0.0.1 only and set OHG_FREELLMAPI_API_KEY (dedicated unified key).
  4. Free quotas can change. If the gateway or quota is unavailable, LLM work is queued and
     deterministic processing continues; no other provider is ever used automatically.
  5. If you cannot establish free-only operation, set llm.provider: local (LM Studio) or
     OHG_LLM_ENABLED=false."""


@dataclass(frozen=True)
class Acknowledgement:
    acknowledged_at: str
    policy_version: str
    provider: str
    model: str


def read_ack(path: Path) -> Acknowledgement | None:
    try:
        d = json.loads(path.read_text())
        return Acknowledgement(d["acknowledged_at"], d["policy_version"], d["provider"], d["model"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_ack(path: Path, clock: Clock, provider: str, model: str) -> Acknowledgement:
    ack = Acknowledgement(iso_z(clock.now_utc()), POLICY_VERSION, provider, model)
    path.write_text(json.dumps(ack.__dict__, indent=2) + "\n")
    path.chmod(0o600)
    return ack


def ack_is_current(path: Path, provider: str) -> bool:
    ack = read_ack(path)
    return ack is not None and ack.policy_version == POLICY_VERSION and ack.provider == provider


def require_ack(path: Path, provider: str) -> None:
    """Gate for any request that could leave the machine. The local provider needs none."""
    if provider == "local":
        return
    if not ack_is_current(path, provider):
        raise LLMUnavailable(
            "external-processing acknowledgement missing or outdated; run `ohg llm ack`"
        )
