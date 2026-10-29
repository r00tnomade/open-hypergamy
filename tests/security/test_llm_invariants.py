"""Cross-module invariants for the LLM route (CLAUDE.md invariants 1, 2, 5)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.helpers_llm import FakeGateway, empty_output

from opportunity_radar.clock import FixedClock
from opportunity_radar.config import load_config
from opportunity_radar.extraction.llm_extractor import LLMExtractionService
from opportunity_radar.llm.ack import write_ack
from opportunity_radar.llm.client import OpenAICompatClient
from opportunity_radar.persistence import db as dbm
from opportunity_radar.persistence import migrations as mig

CLOCK = FixedClock(datetime(2026, 10, 29, 12, 0, tzinfo=UTC))


def test_llm_output_can_never_reach_confirmed_official():
    from datetime import date

    from opportunity_radar.domain.models import CandidateFact, EvidenceQuote
    from opportunity_radar.verification.evidence import ground_facts
    from opportunity_radar.verification.rules import verify_fact

    text = "Applications close on 15 March 2027."
    f = CandidateFact(
        field_name="deadline:application_close", proposed_value={"date": "2027-03-15"},
        evidence=[EvidenceQuote(source_url="https://example.edu/p", excerpt=text,
                                field_name="deadline:application_close")],
        extraction_method="llm",
    )  # fmt: skip
    f = ground_facts([f], text)[0]
    for tier in ("t1_official_program", "t2_official_org"):
        r = verify_fact(f, source_trust_tier=tier, discovery_only=False, url_in_scope=True,
                        today=date(2026, 10, 29), edition_year=2027, distinct_values_for_field=1)  # fmt: skip
        assert not r.confirmed


def test_only_allow_listed_content_leaves_the_machine(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "424242424")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234567:telegram-secret-token-abcdefgh")
    cfg = load_config(home=tmp_path / "private-home", env={})
    cfg.paths.ensure()
    # a "profile" and notes exist on disk; they must not be reachable from the payload
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "profile.yaml").write_text("academic: {institution: SecretUni}\n")
    conn = dbm.connect(cfg.paths.db, create=True)
    mig.migrate(conn, mig.discover(), CLOCK)
    write_ack(cfg.paths.llm_ack, CLOCK, "freellmapi", "auto:radar-free")
    gw = FakeGateway(lambda p: empty_output())
    svc = LLMExtractionService(conn, cfg, CLOCK, OpenAICompatClient(
        "http://127.0.0.1:3001/v1", "auto:radar-free", "key-abcdef", transport=gw.transport,
        forbidden=[str(cfg.paths.home), "424242424", "key-abcdef"]))  # fmt: skip
    svc.extract(url="https://example.edu/p", trust_tier="t2_official_org", authority_scope="a",
                observation_id="o", content_sha256="h", title="T", candidate_title="T",
                text="Applications close on 15 March 2027. Mail ceo@example.edu. See /Users/private/x.",
                known_edition_key=None)  # fmt: skip
    wire = gw.chat_requests[0].content.decode()
    for secret in ("SecretUni", "private-home", "424242424", "telegram-secret", "ceo@example.edu",
                   "/Users/private", "key-abcdef"):  # fmt: skip
        assert secret not in wire, secret
    conn.close()


def test_no_network_client_other_than_loopback_gateway_in_llm_package():
    root = Path(__file__).parents[2] / "src" / "opportunity_radar" / "llm"
    code = "\n".join(p.read_text() for p in root.glob("*.py"))
    assert code.count("httpx.Client(") == 1  # one client, constructed only after the loopback check
    for host in ("openai.com", "anthropic.com", "googleapis.com", "openrouter.ai"):
        assert host not in code


def test_non_loopback_llm_endpoint_cannot_be_configured():
    from opportunity_radar.errors import ConfigurationError

    for provider_env in ({"RADAR_FREELLMAPI_BASE_URL": "https://api.example.com/v1"},
                         {"RADAR_LLM_PROVIDER": "local", "RADAR_LLM_BASE_URL": "http://10.0.0.5:1234/v1"}):  # fmt: skip
        with pytest.raises(ConfigurationError):
            load_config(env=provider_env)
