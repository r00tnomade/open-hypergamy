-- Migration 0005: portfolio class per source, for honest coverage vs the HLD §6.2 targets.
ALTER TABLE sources ADD COLUMN portfolio TEXT;
CREATE INDEX ix_sources_portfolio ON sources(portfolio);
