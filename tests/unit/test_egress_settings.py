"""Static validation of proxy configuration (ADR-012): off by default, explicit trust only."""

import pytest
from pydantic import ValidationError
from tests.helpers_egress import profile, settings

from open_hypergamy.config import Settings, load_config
from open_hypergamy.egress.settings import ProxyProfile, ProxySettings
from open_hypergamy.errors import ConfigurationError


def test_proxies_are_disabled_and_direct_by_default():
    s = Settings().proxy
    assert s.enabled is False and s.profiles == [] and s.default_profiles == []
    assert s.candidates_for("any-source") == [] and s.is_assigned("any-source") is False


def test_a_profile_must_be_explicitly_trusted():
    with pytest.raises(ValidationError, match="not trusted"):
        ProxyProfile(name="p1", url="https://p1.proxy.example.net:8443")


def test_endpoint_host_must_be_on_the_trusted_host_list():
    with pytest.raises(ValidationError, match="trusted_endpoint_hosts"):
        ProxySettings(
            enabled=True,
            profiles=[profile("p1")],
            trusted_endpoint_hosts=["other.example.net"],
            health_check_url="https://health.example.org/ok",
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pw@p1.proxy.example.net:8443",
        "https://p1.proxy.example.net:8443/path",
        "https://p1.proxy.example.net:8443?x=1",
        "https://p1.proxy.example.net",  # no explicit port
        "ftp://p1.proxy.example.net:21",
        "socks4://p1.proxy.example.net:1080",
    ],
)
def test_malformed_or_credential_bearing_urls_are_rejected(url):
    with pytest.raises(ValidationError):
        ProxyProfile(name="p1", url=url, trusted=True)


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.1",
        "169.254.169.254",
        "[::1]",
        "localhost",
        "proxy.internal",
    ],
)
def test_loopback_private_and_metadata_endpoints_need_explicit_permission(host):
    url = f"https://{host}:8443"
    with pytest.raises(ValidationError, match="allow_private_endpoint"):
        ProxyProfile(name="p1", url=url, trusted=True)
    ok = ProxyProfile(name="p1", url=url, trusted=True, allow_private_endpoint=True)
    assert ok.allow_private_endpoint


def test_cleartext_proxy_to_a_public_endpoint_needs_explicit_opt_in():
    for scheme in ("http", "socks5"):
        url = f"{scheme}://p1.proxy.example.net:3128"
        with pytest.raises(ValidationError, match="unencrypted"):
            ProxyProfile(name="p1", url=url, trusted=True)
        assert ProxyProfile(name="p1", url=url, trusted=True, allow_plaintext=True).scheme == scheme
    # a controlled local deployment may use plaintext on loopback
    ProxyProfile(name="p1", url="http://127.0.0.1:3128", trusted=True, allow_private_endpoint=True)


def test_credentials_are_secret_names_set_together():
    with pytest.raises(ValidationError, match="secret names"):
        profile("p1", username_secret="hunter2", password_secret="OHG_PROXY_P1_PASS")
    with pytest.raises(ValidationError, match="both"):
        profile("p1", username_secret="OHG_PROXY_P1_USER")
    p = profile("p1", username_secret="OHG_PROXY_P1_USER", password_secret="OHG_PROXY_P1_PASS")
    assert p.username_secret == "OHG_PROXY_P1_USER"


def test_references_and_health_check_are_validated():
    with pytest.raises(ValidationError, match="unknown proxy profile"):
        settings(default_profiles=["nope"])
    with pytest.raises(ValidationError, match="unknown proxy profile"):
        settings(assignments={"src": ["nope"]})
    with pytest.raises(ValidationError, match="health_check_url"):
        settings(health_check_url=None)
    with pytest.raises(ValidationError, match="health_check_url"):
        settings(health_check_url="http://health.example.org/ok")
    with pytest.raises(ValidationError, match="non-public"):
        settings(health_check_url="https://169.254.169.254/latest")
    with pytest.raises(ValidationError, match="unique"):
        settings(profiles=[profile("p1"), profile("p1")])
    with pytest.raises(ValidationError, match="max_failovers"):
        settings(max_failovers=9)


def test_disabled_profiles_and_sources_resolve_to_nothing():
    s = settings(
        profiles=[profile("p1"), profile("p2", enabled=False)],
        default_profiles=["p1", "p2"],
        assignments={"only-disabled": ["p2"]},
    )
    assert s.candidates_for("x") == ["p1"]
    assert s.candidates_for("only-disabled") == [] and s.is_assigned("only-disabled")
    assert s.candidates_for(None) == []  # unscoped traffic is direct


def test_unknown_keys_fail_instead_of_being_ignored():
    with pytest.raises(ValidationError):
        ProxySettings(enabled=False, rotate_on_403=True)  # type: ignore[call-arg]


def test_pasted_credentials_are_never_echoed_in_config_errors(tmp_path):
    cfg = tmp_path / "settings.yaml"
    cfg.write_text(
        "proxy:\n  enabled: true\n  profiles:\n"
        "    - name: p1\n      url: https://p1.proxy.example.net:8443\n"
        "      trusted: true\n      password: hunter2-SECRET\n"
    )
    with pytest.raises(ConfigurationError) as e:
        load_config(home=tmp_path / "h", config=cfg, env={})
    assert "hunter2" not in str(e.value) and "password" in str(e.value)
    cfg.write_text(
        "proxy:\n  enabled: true\n  profiles:\n"
        "    - name: p1\n      url: https://bob:hunter2-SECRET@p1.proxy.example.net:8443\n"
        "      trusted: true\n"
    )
    with pytest.raises(ConfigurationError) as e:
        load_config(home=tmp_path / "h", config=cfg, env={})
    assert "hunter2" not in str(e.value)
