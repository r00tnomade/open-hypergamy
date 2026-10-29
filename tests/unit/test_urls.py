import pytest

from opportunity_radar.errors import SourcePolicyDenied
from opportunity_radar.sources.urls import canonicalize_url, validate_public_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTPS://Example.EDU:443/a/?utm_source=x&b=1#frag", "https://example.edu/a/?b=1"),
        ("http://example.edu", "http://example.edu/"),
        ("https://example.edu/a?fbclid=1&gclid=2", "https://example.edu/a"),
        ("https://example.edu:8443/x", "https://example.edu:8443/x"),
        ("https://bücher.example/p", "https://xn--bcher-kva.example/p"),
        ("https://example.edu/dir/", "https://example.edu/dir/"),  # trailing slash preserved
        ("https://example.edu/dir", "https://example.edu/dir"),
    ],
)
def test_canonicalize(raw, expected):
    assert canonicalize_url(raw) == expected


def test_relative_resolution():
    assert (
        canonicalize_url("../x?utm_medium=a", base="https://example.edu/a/b/")
        == "https://example.edu/a/x"
    )


@pytest.mark.parametrize(
    "bad",
    [
        "ftp://example.edu/",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "https://user:pw@example.edu/",
        "https:///nohost",
    ],
)
def test_canonicalize_rejects(bad):
    with pytest.raises(SourcePolicyDenied):
        canonicalize_url(bad)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/x",
        "http://[::1]/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data",
        "http://100.64.0.1/",
        "http://[::ffff:127.0.0.1]/",
        "http://printer.local/",
        "http://intranet/",
    ],
)
def test_literal_and_local_targets_blocked(url):
    with pytest.raises(SourcePolicyDenied):
        validate_public_url(url, resolver=lambda h: ["93.184.216.34"])


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "::1", "fd00::1"])
def test_dns_resolving_to_private_blocked(ip):
    with pytest.raises(SourcePolicyDenied, match="non-public"):
        validate_public_url("https://sneaky.example.com/", resolver=lambda h: [ip])


def test_any_private_address_among_several_blocks():
    with pytest.raises(SourcePolicyDenied):
        validate_public_url(
            "https://x.example.com/", resolver=lambda h: ["93.184.216.34", "10.0.0.1"]
        )


def test_public_url_passes_and_scheme_enforced():
    assert (
        validate_public_url("https://example.edu/a#x", resolver=lambda h: ["93.184.216.34"])
        == "https://example.edu/a"
    )
    with pytest.raises(SourcePolicyDenied, match="scheme"):
        validate_public_url(
            "http://example.edu/", permitted_schemes=["https"], resolver=lambda h: ["93.184.216.34"]
        )
