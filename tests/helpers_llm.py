"""Scripted loopback gateway for LLM tests: records every request, never touches the network."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

NULL_TEXT = {"value": None, "evidence": []}
NULL_DATE = {"value": None, "raw_text": None, "timezone": None, "evidence": []}


def empty_output() -> dict[str, Any]:
    return {
        "schema_version": "opportunity_extract.v1",
        "title": dict(NULL_TEXT), "organizer": dict(NULL_TEXT), "category": dict(NULL_TEXT),
        "edition_key": dict(NULL_TEXT), "event_start_date": dict(NULL_DATE),
        "event_end_date": dict(NULL_DATE), "application_open_date": dict(NULL_DATE),
        "application_deadline": {**NULL_DATE, "time_precision": "unknown"},
        "format": {"value": "unknown", "evidence": []}, "location": dict(NULL_TEXT),
        "eligibility_requirements": [], "fee": {"amount_min": None, "amount_max": None,
                                                "currency": None, "evidence": []},
        "funding": {"status": "unknown", "details": None, "evidence": []},
        "ambiguities": [],
    }  # fmt: skip


def seg_of(payload: dict[str, Any], needle: str) -> str:
    for s in payload["observation"]["text_segments"]:
        if needle in s["text"]:
            return str(s["segment_id"])
    raise AssertionError(f"no segment contains {needle!r}")


def ev(payload: dict[str, Any], quote: str) -> list[dict[str, str]]:
    return [{"segment_id": seg_of(payload, quote), "quote": quote}]


class FakeGateway:
    """`responder(payload) -> output dict | str | httpx.Response | Exception`."""

    def __init__(self, responder: Callable[[dict[str, Any]], Any] | None = None,
                 models: list[str] | None = None) -> None:  # fmt: skip
        self.responder = responder or (lambda p: empty_output())
        self.models = models if models is not None else ["auto:ohg-free"]
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)

    @property
    def chat_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path.endswith("/chat/completions")]

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.chat_requests]

    def payloads(self) -> list[dict[str, Any]]:
        return [json.loads(b["messages"][1]["content"]) for b in self.bodies()]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": m} for m in self.models]})
        body = json.loads(request.content)
        result = self.responder(json.loads(body["messages"][1]["content"]))
        if isinstance(result, Exception):
            raise result
        if isinstance(result, httpx.Response):
            return result
        content = result if isinstance(result, str) else json.dumps(result)
        return httpx.Response(200, json={"model": "routed-free-model",
                                         "choices": [{"message": {"content": content}}]})  # fmt: skip
