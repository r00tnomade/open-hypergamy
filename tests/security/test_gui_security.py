"""Security controls of the loopback onboarding server (ADR-014)."""

import json

import httpx
import pytest
from tests.helpers_gui import GOOD_TOKEN, HOST, ORIGIN, PROFILE, fake_keychain, gui, make_gui  # noqa: F401

from open_hypergamy import settings_store
from open_hypergamy.config import load_config
from open_hypergamy.errors import ConfigurationError
from open_hypergamy.gui.app import Request
from open_hypergamy.gui.security import SessionManager
from open_hypergamy.gui.server import GuiServer


def _req(gui, method, path, headers=None, body=b""):
    return gui.app.handle(
        Request(method, path, {k.lower(): v for k, v in (headers or {}).items()}, body)
    )


def test_server_binds_loopback_only_and_works_end_to_end(fake_keychain):
    g = make_gui()
    server = GuiServer(g.service, 0)
    try:
        assert server.httpd.server_address[0] == "127.0.0.1"
        server.start_background()
        base = f"http://127.0.0.1:{server.port}"
        with httpx.Client(follow_redirects=False, trust_env=False) as http:
            r = http.get(server.launch_url())
            assert r.status_code == 303 and r.headers["location"] == "/"
            assert (
                "HttpOnly" in r.headers["set-cookie"]
                and "SameSite=Strict" in r.headers["set-cookie"]
            )
            csrf = http.get(f"{base}/api/session").json()["csrf"]
            h = {"X-OHG-CSRF": csrf, "Origin": base}
            assert http.post(f"{base}/api/profile", json=PROFILE, headers=h).status_code == 200
            assert http.get(f"{base}/").status_code == 200
    finally:
        server.shutdown()


def test_cli_has_no_option_to_listen_elsewhere():
    from typer.testing import CliRunner

    from open_hypergamy.cli import app

    out = CliRunner().invoke(app, ["onboard", "--help"]).output
    assert "--port" in out and "--host" not in out and "--bind" not in out


@pytest.mark.parametrize(
    "host",
    [None, "evil.example:4321", "127.0.0.1:9999", "192.168.1.5:4321", "localhost.evil.com:4321"],
)
def test_host_header_must_be_the_exact_loopback_authority(gui, host):
    c = gui.client()
    r = c.raw("GET", "/api/state", headers={"host": host or ""})
    assert r.status == 421


def test_launch_codes_are_single_use_and_expire(gui):
    code = gui.sessions.issue_launch_code()
    ok = _req(gui, "GET", f"/launch?code={code}", {"host": HOST})
    assert ok.status == 303
    again = _req(gui, "GET", f"/launch?code={code}", {"host": HOST})
    assert again.status == 403 and b"expired" in again.body and "Set-Cookie" not in again.headers
    assert _req(gui, "GET", "/launch?code=guess", {"host": HOST}).status == 403

    clock = [0.0]
    sm = SessionManager(4321, now=lambda: clock[0])
    old = sm.issue_launch_code()
    clock[0] += 301
    assert sm.redeem(old) is None


def test_sessions_expire(gui):
    clock = [0.0]
    sm = SessionManager(4321, now=lambda: clock[0])
    s = sm.redeem(sm.issue_launch_code())
    assert sm.session(s.token) is s
    clock[0] += 12 * 3600 + 1
    assert sm.session(s.token) is None


def test_api_requires_a_session(gui):
    for cookie in (None, "ohg_session=", "ohg_session=forged", "other=1"):
        h = {"host": HOST} | ({"cookie": cookie} if cookie else {})
        assert _req(gui, "GET", "/api/state", h).status == 401
        assert (
            _req(gui, "GET", "/", h).status == 403
        )  # the shell isn't served without a session either


def test_writes_require_origin_csrf_and_json(gui):
    c = gui.client()
    assert c.raw("POST", "/api/profile", PROFILE, {"origin": ""}).status == 403
    assert c.raw("POST", "/api/profile", PROFILE, {"origin": "http://evil.example"}).status == 403
    assert c.raw("POST", "/api/profile", PROFILE, {"origin": "null"}).status == 403
    assert c.raw("POST", "/api/profile", PROFILE, {"x-ohg-csrf": ""}).status == 403
    assert c.raw("POST", "/api/profile", PROFILE, {"x-ohg-csrf": "wrong"}).status == 403
    other = gui.client()  # another session's token is not valid here
    assert c.raw("POST", "/api/profile", PROFILE, {"x-ohg-csrf": other.csrf}).status == 403
    assert c.raw("POST", "/api/profile", PROFILE, {"content-type": "text/plain"}).status == 415
    assert c.raw("POST", "/api/profile", PROFILE).status == 200


def test_security_headers_on_every_response(gui):
    c = gui.client()
    for r in (c.raw("GET", "/api/state"), c.raw("GET", "/"), c.raw("GET", "/api/nope"),
              _req(gui, "GET", "/api/state", {"host": "evil:1"}), c.raw("GET", "/static/brand/favicon.svg")):  # fmt: skip
        assert "default-src 'none'" in r.headers["Content-Security-Policy"]
        assert "script-src 'self'" in r.headers["Content-Security-Policy"]
        assert "'unsafe-inline'" not in r.headers["Content-Security-Policy"]
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["Referrer-Policy"] == "no-referrer"
        assert r.headers["X-Frame-Options"] == "DENY"
    assert c.raw("GET", "/api/state").headers["Cache-Control"] == "no-store"


def test_built_shell_has_no_inline_script_or_external_resource(gui):
    body = gui.client().raw("GET", "/").body.decode()
    assert '<script type="module"' in body and 'src="/static/assets/' in body
    assert "<script>" not in body
    for external in ("http://", "https://", "//fonts.", "googleapis"):
        assert external not in body


@pytest.mark.parametrize(
    "path",
    [
        "/static/../service.py",
        "/static/assets/../../app.py",
        "/static/%2e%2e/app.py",
        "/static/assets/nope.js",
        "/static//etc/passwd",
    ],
)
def test_static_files_cannot_escape_the_asset_dir(gui, path):
    r = gui.client().raw("GET", path)
    assert r.status == 404 and b"def " not in r.body


def test_errors_never_leak_paths_or_tracebacks(gui, monkeypatch):
    c = gui.client()
    monkeypatch.setattr(
        gui.service,
        "summary",
        lambda: (_ for _ in ()).throw(RuntimeError(f"boom in {gui.service.home}")),
    )
    r = c.raw("GET", "/api/summary")
    assert r.status == 500
    assert str(gui.service.home) not in r.body.decode() and "Traceback" not in r.body.decode()
    st = c.get("/api/state")
    assert str(gui.service.home) not in json.dumps(st)  # no filesystem paths in the read model


def test_telegram_errors_are_scrubbed_of_the_token(gui, fake_keychain):
    from open_hypergamy.notifications import telegram as tg

    bad = "123456789:AAEchoedBackByTheApiInTheErrorText_xyz"
    res = tg.check_bot(bad, transport=gui.telegram.transport())
    assert res.rejected and bad not in (res.error or "") and "[REDACTED]" in (res.error or "")


def test_oversized_and_malformed_bodies_are_refused(gui):
    c = gui.client()
    r = c.app.handle(Request("PUT", "/api/draft", {"host": HOST, "cookie": c.cookie, "origin": ORIGIN, "x-ohg-csrf": c.csrf,
                                                    "content-type": "application/json"}, b"{" + b" " * 70_000))  # fmt: skip
    assert r.status == 413
    r = c.app.handle(Request("POST", "/api/profile", {"host": HOST, "cookie": c.cookie, "origin": ORIGIN, "x-ohg-csrf": c.csrf,
                                                      "content-type": "application/json"}, b"{not json"))  # fmt: skip
    assert r.status == 400


def test_settings_store_only_writes_allowlisted_keys(tmp_path):
    cfg = load_config()
    with pytest.raises(ConfigurationError):
        settings_store.update(cfg, {"llm.freellmapi.base_url": "http://evil.example/v1"})
    with pytest.raises(ConfigurationError):
        settings_store.update(cfg, {"telegram.bot_token": GOOD_TOKEN})
    with pytest.raises(ConfigurationError):  # validated as a whole before anything is written
        settings_store.update(cfg, {"schedule.digest_time": "99:99"})
    assert not settings_store.managed_path(cfg).exists()


def test_unexpected_errors_outside_routes_still_get_headers_and_no_traceback(gui, monkeypatch):
    c = gui.client()
    monkeypatch.setattr(
        gui.app, "_asset", lambda *a, **k: (_ for _ in ()).throw(ValueError("embedded null byte"))
    )
    r = c.raw("GET", "/static/x\x00.js")
    assert r.status == 500 and "null byte" not in r.body.decode()
    assert "default-src 'none'" in r.headers["Content-Security-Policy"]


def test_malformed_content_length_is_rejected_over_the_socket(fake_keychain):
    import socket

    g = make_gui()
    server = GuiServer(g.service, 0)
    server.start_background()
    try:
        for length in ("-1", "abc", "99999999"):
            with socket.create_connection(("127.0.0.1", server.port), timeout=5) as s:
                s.sendall(
                    f"POST /api/profile HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\nContent-Length: {length}\r\n\r\n".encode()
                )
                status = s.recv(64).split(b" ")[1]
            assert status in (b"400", b"413"), (length, status)
    finally:
        server.shutdown()


def test_bundled_licences_ship_with_the_assets():
    from importlib import resources

    lic = resources.files("open_hypergamy.gui") / "static" / "licenses"
    notices = (lic / "THIRD_PARTY_NOTICES.txt").read_text()
    for pkg in ("space-grotesk", "ibm-plex-mono", "preact@"):
        assert pkg in notices
    for f in (
        "fontsource-variable__space-grotesk.LICENSE.txt",
        "fontsource__ibm-plex-mono.LICENSE.txt",
    ):
        assert "SIL Open Font License" in (lic / f).read_text() or "OFL" in (lic / f).read_text()
    assert (
        "MIT" in (lic / "preact.LICENSE.txt").read_text()
        or "Permission is hereby granted" in (lic / "preact.LICENSE.txt").read_text()
    )


def test_brand_kit_is_served_and_shipped(gui):
    from importlib import resources

    c = gui.client()
    for path, ctype in (
        ("/static/brand/logo-symbol-auto.svg", "image/svg+xml"),
        ("/static/brand/favicon.svg", "image/svg+xml"),
        ("/static/brand/apple-touch-icon.png", "image/png"),
        ("/favicon.svg", "image/svg+xml"),
        ("/favicon.ico", "image"),
    ):
        r = _req(gui, "GET", path, {"host": HOST})  # no session needed for public assets
        assert r.status == 200 and ctype in r.headers["Content-Type"], path
    assert b"OpenHypergamy" in c.raw("GET", "/static/brand/logo-symbol-auto.svg").body
    shell = c.raw("GET", "/").body.decode()
    assert "/static/brand/favicon.svg" in shell and "/static/brand/favicon.ico" in shell
    brand = resources.files("open_hypergamy.gui") / "static" / "brand"
    assert not (brand / "brand-preview.png").is_file() and not (brand / "README.md").is_file()
