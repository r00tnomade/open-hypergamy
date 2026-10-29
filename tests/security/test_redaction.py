from open_hypergamy.observability.logging import redact


def test_telegram_token_redacted():
    tok = "123456789:AAH-abcdefghijklmnopqrstuvwxyz012345"
    assert tok not in redact(f"POST https://api.telegram.org/bot{tok}/sendMessage failed")


def test_env_secret_redacted(monkeypatch):
    monkeypatch.setenv("OHG_FREELLMAPI_API_KEY", "sk-local-supersecret")
    assert "supersecret" not in redact("auth failed for key sk-local-supersecret")
