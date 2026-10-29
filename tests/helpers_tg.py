"""Telegram test doubles: a scripted Bot API transport and a recording sink."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from open_hypergamy.notifications.base import NotificationMessage, SendResult


class FakeBotApi:
    def __init__(
        self, responder: Callable[[dict[str, Any]], httpx.Response | Exception] | None = None
    ) -> None:
        self.responder = responder or (
            lambda body: httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})
        )
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        r = self.responder(json.loads(request.content))
        if isinstance(r, Exception):
            raise r
        return r

    def texts(self) -> list[str]:
        return [json.loads(r.content)["text"] for r in self.requests]


class RecordingSink:
    """Implements NotificationSink; `results` is consumed in order (default: success)."""

    def __init__(self, results: list[SendResult] | None = None) -> None:
        self.results = list(results or [])
        self.sent: list[tuple[NotificationMessage, str]] = []

    def send(self, message: NotificationMessage, idempotency_key: str) -> SendResult:
        self.sent.append((message, idempotency_key))
        return (
            self.results.pop(0)
            if self.results
            else SendResult(True, message_id=str(len(self.sent)))
        )
