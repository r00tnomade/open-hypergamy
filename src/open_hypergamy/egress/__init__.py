"""Operator-controlled egress proxies for public-source acquisition (ADR-012).

Disabled by default. Direct connections remain the default and the only fallback-free mode:
a source assigned to a proxy never silently falls back to a direct connection.
"""
