"""Run the onboarding GUI against fakes for browser (Playwright) tests. Never touches the network,
the real Keychain, or real Telegram.

    uv run python tests/gui_harness.py --port 8765 --scenario clean
    uv run python tests/gui_harness.py --port 8766 --scenario configured

Launch codes `e2e-0` … `e2e-199` are pre-issued. Telegram sends are appended to
`<tmp>/telegram_sent.jsonl`; the path is printed on start-up.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
GOOD_TOKEN = "123456789:AAE2eTestTokenForPlaywrightOnly_xyz123"
REJECTED_TOKEN = "123456789:AAThisTokenIsRejectedByTheFakeBot_00"


def telegram_transport(log: Path) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        token = req.url.path.split("/")[1].removeprefix("bot")
        method = req.url.path.rsplit("/", 1)[-1]
        if token != GOOD_TOKEN:
            return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})
        if method == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {"username": "ohg_e2e_bot"}})
        if method == "getUpdates":
            chat = {"id": 4242, "type": "private", "first_name": "Ada"}
            return httpx.Response(200, json={"ok": True, "result": [{"message": {"chat": chat}}]})
        if method == "sendMessage":
            with log.open("a") as f:
                f.write(json.dumps(json.loads(req.content)) + "\n")
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
        return httpx.Response(404, json={"ok": False, "description": "Not Found"})

    return httpx.MockTransport(handler)


class FakeLLM:
    model = "auto:ohg-free"
    last_model: str | None = None

    def healthy(self) -> bool:
        return True

    def list_models(self) -> list[str]:
        return ["auto:ohg-free"]

    def complete_json(self, **_: Any) -> dict[str, Any]:
        self.last_model = "free-tier/test-model"
        return {"ok": True}

    def close(self) -> None:
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--scenario", choices=["clean", "configured"], default="clean")
    ap.add_argument("--state-dir", type=Path, help="Wiped and reused (default: a new temp dir).")
    args = ap.parse_args()

    if args.state_dir:
        tmp = args.state_dir.resolve()
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
    else:
        tmp = Path(tempfile.mkdtemp(prefix=f"ohg-e2e-{args.scenario}-"))
    for k in list(os.environ):
        if k.startswith(("OHG_", "TELEGRAM_")):
            del os.environ[k]
    os.environ["OHG_HOME"] = str(tmp / "home")
    os.chdir(tmp)  # keep any ./config/settings.yaml out of the run
    sys.path.insert(0, str(ROOT / "src"))

    from open_hypergamy import keychain
    from open_hypergamy.gui.server import GuiServer
    from open_hypergamy.gui.service import Deps, OnboardingService

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

    keychain._runner = runner
    keychain.keychain_enabled = lambda: True  # type: ignore[assignment]
    keychain.clear_cache()

    sent = tmp / "telegram_sent.jsonl"
    sent.touch()
    service = OnboardingService(
        deps=Deps(telegram_transport=telegram_transport(sent), llm_client=lambda _cfg: FakeLLM())
    )
    service.start()
    if args.scenario == "configured":
        home = Path(os.environ["OHG_HOME"])
        (home / "profile.yaml").write_text(
            (ROOT / "tests" / "fixtures" / "profile.yaml").read_text()
        )
        store["TELEGRAM_BOT_TOKEN"], store["TELEGRAM_CHAT_ID"] = GOOD_TOKEN, "4242"
        service.snapshot()  # adopt the existing profile into onboarding state
        st = __import__("open_hypergamy.gui.state", fromlist=["x"])
        s = st.load(home)
        s.completed_at, s.current_step = "2026-10-01T00:00:00Z", "review"
        st.save(home, s, "2026-10-01T00:00:00Z")

    server = GuiServer(service, args.port)
    for i in range(200):
        server.sessions.issue_launch_code(f"e2e-{i}")
    print(f"harness ready on http://127.0.0.1:{server.port} (sent log: {sent})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
