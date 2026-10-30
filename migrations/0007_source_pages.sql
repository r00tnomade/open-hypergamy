-- Migration 0007: independently tracked child pages per source (ADR-011).
-- Observations stay the evidence log; this table only holds per-URL revalidation state.
-- Rows are never deleted on failure: a page that vanishes becomes 'missing', not forgotten.
CREATE TABLE source_pages (
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    canonical_url TEXT NOT NULL,
    depth INTEGER NOT NULL CHECK(depth >= 1),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','missing','held','invalid')),
    status_reason TEXT,
    first_seen_at TEXT NOT NULL,
    last_listed_at TEXT,
    last_attempt_at TEXT,
    last_checked_at TEXT,
    last_changed_at TEXT,
    next_check_at TEXT NOT NULL,
    consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK(consecutive_failures >= 0),
    last_http_status INTEGER,
    last_error_code TEXT,
    etag TEXT,
    last_modified TEXT,
    content_hash TEXT,
    PRIMARY KEY (source_id, canonical_url)
);
CREATE INDEX ix_source_pages_due ON source_pages(source_id, status, next_check_at);

-- Adopt children already observed before this migration. They become due immediately, so the
-- first run after upgrade sends one conditional request each (a 304 when nothing changed).
INSERT INTO source_pages(source_id, canonical_url, depth, status, first_seen_at, last_checked_at,
                         last_changed_at, next_check_at, last_http_status, etag, last_modified,
                         content_hash)
SELECT source_id, canonical_url, 1, 'active', first_seen, retrieved_at, retrieved_at,
       retrieved_at, http_status, etag, last_modified, content_hash
FROM (
    SELECT o.source_id, o.canonical_url, o.retrieved_at, o.http_status, o.etag, o.last_modified,
           o.content_hash,
           MIN(o.created_at) OVER (PARTITION BY o.source_id, o.canonical_url) AS first_seen,
           ROW_NUMBER() OVER (PARTITION BY o.source_id, o.canonical_url
                              ORDER BY o.retrieved_at DESC, o.created_at DESC) AS rn
    FROM source_observations o
    JOIN sources s ON s.id = o.source_id
    WHERE o.canonical_url <> s.canonical_url
)
WHERE rn = 1;
