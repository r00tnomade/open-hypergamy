import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    import os

    for k in list(os.environ):
        if k.startswith("OHG_") or k.startswith("TELEGRAM_"):
            monkeypatch.delenv(k)
    monkeypatch.chdir(tmp_path)  # keep a stray config/settings.yaml from leaking in
    monkeypatch.setenv("OHG_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHG_USE_KEYCHAIN", "0")  # tests never touch the real Keychain
    monkeypatch.setenv("OHG_TELEGRAM_SEND_DELAY_SECONDS", "0")  # never really sleep between sends
