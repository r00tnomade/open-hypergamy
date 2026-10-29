-- Migration 0004: manual-action lock, profile version on snapshots, stored notification text
-- (LLD §11, §12, §13.4). Pending/retrying messages need their body, not just a preview.
ALTER TABLE editions ADD COLUMN action_locked INTEGER NOT NULL DEFAULT 0 CHECK(action_locked IN (0,1));
ALTER TABLE score_snapshots ADD COLUMN profile_version TEXT;
ALTER TABLE notification_log ADD COLUMN message_text TEXT NOT NULL DEFAULT '';
CREATE INDEX ix_snapshots_latest ON score_snapshots(edition_id, created_at DESC);
