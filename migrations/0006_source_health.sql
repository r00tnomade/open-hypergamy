-- Migration 0006: source health fields that cannot be derived from check history (ADR-009).
-- The health state itself is computed (sources/health.py); only these inputs are stored.
ALTER TABLE sources ADD COLUMN cooldown_until TEXT;
ALTER TABLE sources ADD COLUMN last_error_category TEXT;
ALTER TABLE sources ADD COLUMN blocked_reason TEXT;
ALTER TABLE sources ADD COLUMN blocked_at TEXT;
