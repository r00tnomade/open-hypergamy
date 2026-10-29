"""Quote grounding (LLD §9.5): a quote must be a literal substring after safe whitespace folding."""

from __future__ import annotations

import hashlib

from open_hypergamy.domain.models import CandidateFact


def normalize_ws(text: str) -> str:
    return " ".join(text.split())


def quote_grounded(source_text: str, quote: str) -> bool:
    q = normalize_ws(quote)
    return bool(q) and q in normalize_ws(source_text)


def excerpt_sha256(excerpt: str) -> str:
    return hashlib.sha256(normalize_ws(excerpt).encode()).hexdigest()


def ground_facts(facts: list[CandidateFact], text: str) -> list[CandidateFact]:
    """The single choke point that sets `grounded`; ungrounded facts are flagged for review."""
    out: list[CandidateFact] = []
    for f in facts:
        ok = bool(f.evidence) and all(quote_grounded(text, e.excerpt) for e in f.evidence)
        out.append(f.model_copy(update={"grounded": ok}))
    return out
