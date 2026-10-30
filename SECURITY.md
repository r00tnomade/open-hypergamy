# Security policy

## Reporting a vulnerability

Please report security issues **privately** through GitHub's [private vulnerability reporting](https://github.com/r00tnomade/open-hypergamy/security/advisories/new), not in a public issue. Include steps to reproduce and the affected version or commit. You should get a first response within a week.

## In scope

- **SSRF or crawl-scope escapes**: requests reaching loopback, private or link-local addresses, including via DNS or redirects, or links escaping a source's domain and path rules.
- **Data leaks**: secrets, the local profile, file paths or Telegram IDs reaching logs, exceptions or the LLM payload.
- **Verification bypass**: any path that lets LLM output, an aggregator or a manual entry mark a fact `confirmed_official`, or an ungrounded quote pass the grounding check.
- **Unsafe parsing**: XML, feed or HTML input that causes code execution, entity expansion or unbounded memory use.

## Out of scope

How you choose to use the tool against third-party sites. See the [Security and responsible use](README.md#security-and-responsible-use) notice.

## Supported versions

Only the latest commit on `main` is supported while the project is pre-1.0.
