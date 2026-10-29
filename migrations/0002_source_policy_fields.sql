-- Migration 0002: source crawl policy, discovery-only flag and policy-override audit (LLD §6.1, §6.2).
ALTER TABLE sources ADD COLUMN discovery_policy_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE sources ADD COLUMN extraction_hints_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE sources ADD COLUMN discovery_only INTEGER NOT NULL DEFAULT 0 CHECK(discovery_only IN (0,1));
ALTER TABLE sources ADD COLUMN policy_override_at TEXT;
