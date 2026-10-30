-- Migration 0008: per-check egress diagnostics (ADR-012). Names and counters only: never proxy
-- addresses, credentials or URLs. One row per source check that used (or tried) a proxy.
CREATE TABLE source_check_egress (
    source_check_run_id TEXT PRIMARY KEY REFERENCES source_check_runs(id) ON DELETE CASCADE,
    profile TEXT,
    rotation_count INTEGER NOT NULL DEFAULT 0,
    failover_count INTEGER NOT NULL DEFAULT 0,
    proxy_latency_ms INTEGER,
    destination_status INTEGER,
    detail_json TEXT NOT NULL DEFAULT '{}'
);
