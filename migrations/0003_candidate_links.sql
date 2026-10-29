-- Migration 0003: candidate -> edition link and dedupe keys (LLD §8.3, §8.4).
ALTER TABLE candidates ADD COLUMN promoted_edition_id TEXT REFERENCES editions(id) ON DELETE SET NULL;
ALTER TABLE candidates ADD COLUMN organizer_domain TEXT;
ALTER TABLE candidates ADD COLUMN edition_key TEXT;
CREATE INDEX ix_candidates_org_key ON candidates(organizer_domain, edition_key);
CREATE INDEX ix_candidates_edition ON candidates(promoted_edition_id);
CREATE UNIQUE INDEX ux_programs_org_name ON programs(organization_id, normalized_name) WHERE organization_id IS NOT NULL;
