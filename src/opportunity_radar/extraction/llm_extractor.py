"""LLM-assisted extraction with deterministic grounding (LLD §9.1, §9.5).

The model proposes; this module disposes. Every accepted value must cite a segment from the
exact payload, quote it verbatim, and (for dates, amounts, formats) have the quote actually
contain the value. Whatever survives becomes an *unverified* claim: `verify_fact` caps
`llm` facts below `confirmed_official`, so the model can never confirm anything.
"""

from __future__ import annotations

import contextlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date

from pydantic import ValidationError

from opportunity_radar.clock import Clock, iso_z
from opportunity_radar.config import LoadedConfig
from opportunity_radar.domain.models import CandidateFact, EvidenceQuote
from opportunity_radar.errors import LLMInvalidResponse, LLMUnavailable
from opportunity_radar.extraction.dates import EVENT, classify_context, find_dates
from opportunity_radar.keychain import get_secret
from opportunity_radar.llm.ack import require_ack
from opportunity_radar.llm.cache import LLMCache
from opportunity_radar.llm.client import LLMClient, OpenAICompatClient
from opportunity_radar.llm.prompts import (
    PROMPT_VERSION,
    build_payload,
    cache_key,
    normalized_input_sha256,
    system_message,
)
from opportunity_radar.llm.redact import redact
from opportunity_radar.llm.schemas import OpportunityExtract
from opportunity_radar.verification.evidence import normalize_ws

MAX_SEGMENT_CHARS = 1200
_RELEVANT = re.compile(
    r"apply|application|deadline|eligib|require|must|open to|student|enrol|bachelor|master|ph\.?d|"
    r"fee|cost|free of|fund|scholar|stipend|travel|accommodation|location|venue|online|hybrid|"
    r"in[- ]person|dates?\b|takes place|bewerb|frist|teilnahme",
    re.I,
)
_FORMAT_WORDS = {
    "hybrid": r"hybrid",
    "online": r"online|virtual|remote|zoom|webinar",
    "in_person": r"in[- ]person|on[- ]site|presence|vor ort|venue|campus|lab|city|hosted at",
}
_FREE = re.compile(r"free of charge|no fee|without charge|kostenlos|gratis|no cost|free\b", re.I)


@dataclass
class LLMStats:
    calls: int = 0
    cache_hits: int = 0
    malformed: int = 0
    unavailable: int = 0
    claims_accepted: int = 0
    claims_rejected: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(vars(self))


@dataclass
class LLMOutcome:
    facts: list[CandidateFact] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)
    cache_hit: bool = False
    model: str = ""


def build_segments(text: str, max_chars: int) -> list[dict[str, str]]:
    """Relevant paragraphs first (dates/keywords), original order restored, hard char budget."""
    paras: list[tuple[str, str]] = []
    heading = ""
    for line in (ln.strip() for ln in text.splitlines()):
        if not line:
            continue
        if len(line) <= 70 and not re.search(r"[.!?:]$", line) and not find_dates(line):
            heading = line
            continue
        while len(line) > MAX_SEGMENT_CHARS:  # split on a sentence boundary where possible
            cut = line.rfind(". ", 0, MAX_SEGMENT_CHARS)
            cut = cut + 1 if cut > 200 else MAX_SEGMENT_CHARS
            paras.append((heading, line[:cut].strip()))
            line = line[cut:].strip()
        paras.append((heading, line))
    scored = sorted(
        range(len(paras)),
        key=lambda i: (
            -(
                3 * len(find_dates(paras[i][1]))
                + len(_RELEVANT.findall(paras[i][1]))
                + (2 if i == 0 else 0)
            ),
            i,
        ),
    )
    chosen: list[int] = []
    used = 0
    for i in scored:
        cost = len(paras[i][0]) + len(paras[i][1]) + 60  # JSON keys/ids overhead
        if used + cost > max_chars:
            continue
        chosen.append(i)
        used += cost
    out = []
    for n, i in enumerate(sorted(chosen), start=1):
        h, body = paras[i]
        out.append({"segment_id": f"s{n}", "heading": redact(h).text, "text": redact(body).text})
    return out


def _number_candidates(quote: str) -> set[float]:
    found: set[float] = set()
    for m in re.finditer(r"\d[\d.,\s]*\d|\d", quote):
        raw = m.group(0).strip()
        for variant in (
            raw.replace(" ", "").replace(",", ""),
            raw.replace(" ", "").replace(".", "").replace(",", "."),
        ):
            with contextlib.suppress(ValueError):
                found.add(float(variant))
    return found


class _Grounder:
    def __init__(self, segments: dict[str, str], url: str, obs_id: str | None, model: str) -> None:
        self.seg = {k: normalize_ws(v) for k, v in segments.items()}
        self.url, self.obs_id, self.model = url, obs_id, model
        self.facts: list[CandidateFact] = []
        self.rejected: list[str] = []

    def quotes(self, field_name: str, evidence: list) -> list[str] | None:  # type: ignore[type-arg]
        """Verbatim quotes if every evidence item is grounded in its cited segment, else None."""
        if not evidence:
            self.rejected.append(f"{field_name}: no_evidence")
            return None
        out = []
        for ev in evidence:
            seg = self.seg.get(ev.segment_id)
            if seg is None:
                self.rejected.append(f"{field_name}: unknown_segment")
                return None
            q = normalize_ws(ev.quote)
            if not q or q not in seg:
                self.rejected.append(f"{field_name}: quote_not_in_segment")
                return None
            out.append(q)
        return out

    def add(self, name: str, value: object, quote: str, raw: str | None = None) -> None:
        self.facts.append(
            CandidateFact(
                field_name=name,
                proposed_value=value,
                raw_text=raw,
                evidence=[
                    EvidenceQuote(
                        source_url=self.url,
                        observation_id=self.obs_id,
                        excerpt=quote,
                        field_name=name,
                    )
                ],
                extraction_method="llm",
                model_name=self.model,
                prompt_version=PROMPT_VERSION,
            )
        )

    def text(self, out_name: str, f) -> None:  # type: ignore[no-untyped-def]
        if not f.value:
            return
        qs = self.quotes(out_name, f.evidence)
        if qs:
            self.add(out_name, {"value": f.value}, qs[0], f.value)

    def date(self, out_name: str, f, expected: str) -> None:  # type: ignore[no-untyped-def]
        if f.value is None:
            return
        want = date.fromisoformat(f.value)
        qs = self.quotes(out_name, f.evidence)
        if not qs:
            return
        for q in qs:
            for m in find_dates(q):
                if not m.usable or want not in (m.start, m.end):
                    continue
                ctx = classify_context(q, m)
                if ctx not in (None, expected):  # quote says it is a different kind of date
                    self.rejected.append(f"{out_name}: context_mismatch({ctx})")
                    return
                payload = {
                    "date": f.value,
                    "raw": m.raw,
                    "precision": m.precision,
                    "context": expected,
                    "ambiguity": None,
                }
                self.add(out_name, payload, q, m.raw)
                return
        self.rejected.append(f"{out_name}: quote_does_not_contain_value")


def ground_output(
    out: OpportunityExtract,
    segments: list[dict[str, str]],
    *,
    url: str,
    observation_id: str | None,
    model: str,
) -> LLMOutcome:
    g = _Grounder({s["segment_id"]: s["text"] for s in segments}, url, observation_id, model)
    g.date("event_start_date", out.event_start_date, EVENT)
    g.date("event_end_date", out.event_end_date, EVENT)
    g.date("deadline:application_open", out.application_open_date, "application_open")
    g.date("deadline:application_close", out.application_deadline, "application_close")
    g.text("category", out.category)
    g.text("location", out.location)
    g.text("organizer", out.organizer)
    g.text("edition_key", out.edition_key)
    if out.format.value != "unknown":
        qs = g.quotes("format", out.format.evidence)
        if qs and any(re.search(_FORMAT_WORDS[out.format.value], q, re.I) for q in qs):
            g.add("format", {"value": out.format.value}, qs[0])
        elif qs:
            g.rejected.append("format: quote_does_not_support_value")
    for req in out.eligibility_requirements:
        qs = g.quotes("eligibility", req.evidence)
        if qs:
            g.add("eligibility", {"value": req.requirement, "blocking": req.blocking}, qs[0])
    fee = out.fee
    amounts = [a for a in (fee.amount_min, fee.amount_max) if a is not None]
    if amounts:
        qs = g.quotes("fee", fee.evidence)
        if qs:
            nums = set().union(*(_number_candidates(q) for q in qs))
            if all((a == 0 and any(_FREE.search(q) for q in qs)) or a in nums for a in amounts):
                g.add(
                    "fee",
                    {"min": fee.amount_min, "max": fee.amount_max, "currency": fee.currency},
                    qs[0],
                )
            else:
                g.rejected.append("fee: quote_does_not_contain_amount")
    if out.funding.status != "unknown":
        qs = g.quotes("funding", out.funding.evidence)
        if qs:
            g.add("funding", {"status": out.funding.status, "details": out.funding.details}, qs[0])
    return LLMOutcome(
        facts=g.facts, rejected=g.rejected, ambiguities=out.ambiguities[:20], model=model
    )


class LLMExtractionService:
    def __init__(
        self, conn: sqlite3.Connection, cfg: LoadedConfig, clock: Clock, client: LLMClient
    ) -> None:
        self.conn, self.cfg, self.clock, self.client = conn, cfg, clock, client
        llm = cfg.settings.llm
        self.provider = llm.provider
        self.cache = LLMCache(conn, clock, llm.provider) if llm.extraction_cache else None
        self.stats = LLMStats()

    def extract(
        self,
        *,
        url: str,
        trust_tier: str,
        authority_scope: str,
        observation_id: str,
        content_sha256: str,
        title: str,
        text: str,
        candidate_title: str,
        known_edition_key: str | None,
    ) -> LLMOutcome:
        llm = self.cfg.settings.llm
        require_ack(self.cfg.paths.llm_ack, self.provider)
        segments = build_segments(text, llm.active.max_input_chars)
        payload = build_payload(
            url=url,
            trust_tier=trust_tier,
            authority_scope=redact(authority_scope).text,
            observation_id=observation_id,
            retrieved_at=iso_z(self.clock.now_utc()),
            content_sha256=content_sha256,
            title=redact(title).text,
            segments=segments,
            title_guess=redact(candidate_title).text,
            known_edition_key=known_edition_key,
        )
        while (
            len(json.dumps(payload, ensure_ascii=False)) > llm.active.max_input_chars and segments
        ):
            segments.pop()  # hard input budget (LLD §9.2)
            payload["observation"]["text_segments"] = segments
        key = cache_key(llm.active.model, payload)
        parsed: OpportunityExtract | None = None
        cache_hit = False
        if self.cache and (hit := self.cache.get(key)) is not None:
            try:
                parsed = OpportunityExtract.model_validate(hit)
                self.stats.cache_hits += 1
                cache_hit = True
            except ValidationError:
                parsed = None
        routed = llm.active.model
        if parsed is None:
            if self.stats.calls >= llm.max_calls_per_run:
                raise LLMUnavailable("per-run LLM call budget reached; work stays queued")
            for _ in range(1 + llm.max_retries):
                self.stats.calls += 1
                try:
                    raw = self.client.complete_json(
                        system_prompt=system_message(),
                        user_payload=payload,
                        schema=OpportunityExtract.model_json_schema(),
                        cache_key=key,
                    )
                except LLMUnavailable:
                    self.stats.unavailable += 1
                    raise
                except LLMInvalidResponse:
                    self.stats.malformed += 1
                    continue
                routed = self.client.last_model or routed
                try:
                    parsed = OpportunityExtract.model_validate(raw)
                except ValidationError:
                    self.stats.malformed += 1
                    if self.cache:
                        self.cache.put(
                            key,
                            model=llm.active.model,
                            prompt_version=PROMPT_VERSION,
                            input_sha256=normalized_input_sha256(payload),
                            response=raw,
                            status="invalid",
                        )
                    continue
                if self.cache:
                    self.cache.put(
                        key,
                        model=llm.active.model,
                        prompt_version=PROMPT_VERSION,
                        input_sha256=normalized_input_sha256(payload),
                        response=parsed.model_dump(),
                        status="valid",
                    )
                break
            if parsed is None:
                raise LLMInvalidResponse("model output failed schema validation after retries")
        outcome = ground_output(
            parsed, segments, url=url, observation_id=observation_id, model=routed
        )
        outcome.cache_hit = cache_hit
        self.stats.claims_accepted += len(outcome.facts)
        self.stats.claims_rejected += len(outcome.rejected)
        return outcome


def llm_enabled(cfg: LoadedConfig) -> bool:
    llm = cfg.settings.llm
    if not llm.enabled:
        return False
    return not (llm.provider == "freellmapi" and not llm.allow_remote_public_content)


def build_client(cfg: LoadedConfig) -> OpenAICompatClient:
    llm = cfg.settings.llm
    key = get_secret(llm.freellmapi.api_key_env) if llm.provider == "freellmapi" else None
    forbidden = [
        str(cfg.paths.home),
        key or "",
        get_secret("TELEGRAM_BOT_TOKEN"),
        get_secret("TELEGRAM_CHAT_ID"),
    ]
    return OpenAICompatClient(
        llm.active.base_url,
        llm.active.model,
        key,
        timeout=llm.timeout_seconds,
        temperature=llm.temperature,
        max_tokens=llm.max_output_tokens,
        forbidden=forbidden,
        require_key=llm.provider == "freellmapi",
    )


def build_llm_service(
    conn: sqlite3.Connection, cfg: LoadedConfig, clock: Clock, *, client: LLMClient | None = None
) -> LLMExtractionService | None:
    """None when the LLM route is disabled (deterministic processing only; nothing is queued)."""
    if not llm_enabled(cfg):
        return None
    return LLMExtractionService(conn, cfg, clock, client or build_client(cfg))
