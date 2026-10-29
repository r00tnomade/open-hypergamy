import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    import os

    for k in list(os.environ):
        if k.startswith("RADAR_") or k.startswith("TELEGRAM_"):
            monkeypatch.delenv(k)
    monkeypatch.chdir(tmp_path)  # keep a stray config/settings.yaml from leaking in
    monkeypatch.setenv("RADAR_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("RADAR_TELEGRAM_SEND_DELAY_SECONDS", "0")  # never really sleep between sends
