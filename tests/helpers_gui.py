"""Fixtures for the onboarding GUI: an in-process client over `GuiApp.handle` plus fakes for the
Keychain, the Telegram Bot API and the LLM gateway. Nothing touches the network or the real
Keychain."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from open_hypergamy import keychain
from open_hypergamy.gui.app import GuiApp, Request, Response
from open_hypergamy.gui.security import SessionManager
from open_hypergamy.gui.service import Deps, OnboardingService

PORT = 4321
HOST = f"127.0.0.1:{PORT}"
ORIGIN = f"http://{HOST}"
GOOD_TOKEN = "123456789:AAGoodTokenForTestsOnly_abcdefghijklm"
BAD_TOKEN = "123456789:AARejectedTokenForTestsOnly_abcdefgh"


@dataclass
class FakeTelegram:
    chats: list[dict[str, Any]] = field(
        default_factory=lambda: [{"id": 4242, "type": "private", "first_name": "Ada"}]
    )
    sent: list[dict[str, Any]] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    down: bool = False

    def transport(self) -> httpx.MockTransport:
        def handler(req: httpx.Request) -> httpx.Response:
            self.calls.append(req.url.path.rsplit("/", 1)[-1])
            if self.down:
                raise httpx.ConnectError("connection refused", request=req)
            token = req.url.path.split("/")[1].removeprefix("bot")
            method = req.url.path.rsplit("/", 1)[-1]
            if token != GOOD_TOKEN:
                return httpx.Response(
                    401, json={"ok": False, "description": f"Unauthorized for {token}"}
                )
            if method == "getMe":
                return httpx.Response(200, json={"ok": True, "result": {"username": "test_bot"}})
            if method == "getUpdates":
                return httpx.Response(
                    200, json={"ok": True, "result": [{"message": {"chat": c}} for c in self.chats]}
                )
            if method == "sendMessage":
                self.sent.append(json.loads(req.content))
                return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})
            return httpx.Response(404, json={"ok": False})

        return httpx.MockTransport(handler)


@dataclass
class FakeLLM:
    reachable: bool = True
    models: list[str] = field(default_factory=lambda: ["auto:ohg-free"])
    requests: list[dict[str, Any]] = field(default_factory=list)
    model: str = "auto:ohg-free"
    last_model: str | None = None

    def healthy(self) -> bool:
        return self.reachable

    def list_models(self) -> list[str]:
        return self.models

    def complete_json(self, **kw: Any) -> dict[str, Any]:
        self.requests.append(kw)
        self.last_model = "free/test"
        return {"ok": True}

    def close(self) -> None:
        pass


class Client:
    def __init__(self, app: GuiApp, sessions: SessionManager) -> None:
        self.app, self.sessions = app, sessions
        r = app.handle(
            Request("GET", f"/launch?code={sessions.issue_launch_code()}", {"host": HOST})
        )
        assert r.status == 303
        self.cookie = r.headers["Set-Cookie"].split(";")[0]
        self.csrf = json.loads(self.raw("GET", "/api/session").body)["csrf"]

    def raw(
        self, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None
    ) -> Response:
        h = {"host": HOST, "cookie": self.cookie}
        if method != "GET":
            h |= {
                "origin": ORIGIN,
                "x-ohg-csrf": getattr(self, "csrf", ""),
                "content-type": "application/json",
            }
        h |= headers or {}
        data = b"" if body is None else json.dumps(body).encode()
        return self.app.handle(Request(method, path, {k.lower(): v for k, v in h.items()}, data))

    def call(self, method: str, path: str, body: Any = None, expect: int = 200) -> dict[str, Any]:
        r = self.raw(method, path, body)
        assert r.status == expect, (r.status, r.body)
        return json.loads(r.body)

    def get(self, path: str, expect: int = 200) -> dict[str, Any]:
        return self.call("GET", path, expect=expect)

    def post(self, path: str, body: Any = None, expect: int = 200) -> dict[str, Any]:
        return self.call("POST", path, {} if body is None else body, expect)


@pytest.fixture
def fake_keychain(monkeypatch):
    store: dict[str, str] = {}

    def runner(argv: list[str], _stdin: str | None) -> tuple[int, str]:
        op, name = argv[0], argv[argv.index("-a") + 1]
        if op == "add-generic-password":
            store[name] = argv[argv.index("-w") + 1]
            return 0, ""
        if op == "find-generic-password":
            return (0, store[name]) if name in store else (44, "")
        if op == "delete-generic-password":
            return (0, "") if store.pop(name, None) is not None else (44, "")
        return 1, ""

    monkeypatch.setattr(keychain, "_runner", runner)
    monkeypatch.setattr(keychain, "keychain_enabled", lambda: True)
    keychain.clear_cache()
    yield store
    keychain.clear_cache()


@dataclass
class Gui:
    service: OnboardingService
    app: GuiApp
    sessions: SessionManager
    telegram: FakeTelegram
    llm: FakeLLM

    def client(self) -> Client:
        return Client(self.app, self.sessions)

    def restart(self) -> Gui:
        """A fresh process: new service, new sessions, same OHG_HOME."""
        return make_gui(self.telegram, self.llm)


def make_gui(tg: FakeTelegram | None = None, llm: FakeLLM | None = None) -> Gui:
    tg, llm = tg or FakeTelegram(), llm or FakeLLM()
    service = OnboardingService(
        deps=Deps(telegram_transport=tg.transport(), llm_client=lambda _cfg: llm)
    )
    service.start()
    sessions = SessionManager(PORT)
    return Gui(service, GuiApp(service, sessions), sessions, tg, llm)


@pytest.fixture
def gui(fake_keychain) -> Gui:
    return make_gui()


PROFILE = {
    "degree_level": "bachelor",
    "country": "de",
    "current_year": 2,
    "research_tags": ["robotics", "Reinforcement Learning"],
    "subject_tags": ["computer_science"],
}
