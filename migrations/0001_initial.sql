-- Opportunity Radar migration 0001: initial schema (LLD v1.2 §4.1). Immutable once applied.
PRAGMA foreign_keys = ON;

CREATE TABLE organizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    canonical_domain TEXT,
    country_code TEXT,
    organization_type TEXT NOT NULL DEFAULT 'unknown',
    homepage_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(canonical_domain, name)
);

CREATE TABLE sources (
    id TEXT PRIMARY KEY,
    source_key TEXT UNIQUE,
    organization_id TEXT REFERENCES organizations(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    canonical_url TEXT NOT NULL UNIQUE,
    domain TEXT NOT NULL,
    source_type TEXT NOT NULL,
    adapter_type TEXT NOT NULL,
    trust_tier TEXT NOT NULL CHECK (trust_tier IN (
        't1_official_program','t2_official_org','t3_trusted_listing','t4_aggregator','t5_community'
    )),
    authority_scope TEXT NOT NULL DEFAULT '',
    topic_tags_json TEXT NOT NULL DEFAULT '[]',
    geographic_scope_json TEXT NOT NULL DEFAULT '[]',
    language_codes_json TEXT NOT NULL DEFAULT '[]',
    allowed_domains_json TEXT NOT NULL DEFAULT '[]',
    allow_paths_json TEXT NOT NULL DEFAULT '[]',
    deny_paths_json TEXT NOT NULL DEFAULT '[]',
    terms_review_note TEXT NOT NULL DEFAULT '',
    robots_policy_checked_at TEXT,
    fetch_interval_hours INTEGER NOT NULL DEFAULT 168 CHECK(fetch_interval_hours > 0),
    priority INTEGER NOT NULL DEFAULT 50 CHECK(priority BETWEEN 0 AND 100),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    state TEXT NOT NULL DEFAULT 'active' CHECK(state IN ('active','paused','retired','review_required')),
    last_attempt_at TEXT,
    last_success_at TEXT,
    last_content_change_at TEXT,
    next_due_at TEXT,
    failure_streak INTEGER NOT NULL DEFAULT 0 CHECK(failure_streak >= 0),
    last_http_status INTEGER,
    etag TEXT,
    last_modified TEXT,
    last_content_hash TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX ix_sources_due ON sources(enabled, state, next_due_at, priority DESC);
CREATE INDEX ix_sources_domain ON sources(domain);
CREATE INDEX ix_sources_org ON sources(organization_id);

CREATE TABLE job_runs (
    id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    trigger_type TEXT NOT NULL CHECK(trigger_type IN ('manual','launchd','recovery')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK(status IN ('running','success','partial','failed','cancelled')),
    sources_considered INTEGER NOT NULL DEFAULT 0,
    sources_succeeded INTEGER NOT NULL DEFAULT 0,
    sources_failed INTEGER NOT NULL DEFAULT 0,
    candidates_found INTEGER NOT NULL DEFAULT 0,
    editions_changed INTEGER NOT NULL DEFAULT 0,
    notifications_queued INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT,
    error_summary TEXT
);
CREATE INDEX ix_job_runs_started ON job_runs(started_at DESC);
CREATE INDEX ix_job_runs_type_status ON job_runs(job_type, status, started_at DESC);

CREATE TABLE source_check_runs (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    job_run_id TEXT REFERENCES job_runs(id) ON DELETE SET NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK(status IN ('success','not_modified','partial','blocked_policy','failed','skipped')),
    http_status INTEGER,
    final_url TEXT,
    elapsed_ms INTEGER,
    bytes_received INTEGER,
    retry_count INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT,
    extracted_text_hash TEXT,
    error_code TEXT,
    error_detail_redacted TEXT
);
CREATE INDEX ix_source_check_source_time ON source_check_runs(source_id, started_at DESC);
CREATE INDEX ix_source_check_status_time ON source_check_runs(status, started_at DESC);

CREATE TABLE source_observations (
    id TEXT PRIMARY KEY,
    source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
    source_check_run_id TEXT REFERENCES source_check_runs(id) ON DELETE SET NULL,
    canonical_url TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    http_status INTEGER,
    mime_type TEXT,
    etag TEXT,
    last_modified TEXT,
    content_hash TEXT NOT NULL,
    extracted_text_hash TEXT,
    body_cache_relpath TEXT,
    text_cache_relpath TEXT,
    title TEXT,
    language_code TEXT,
    observed_page_type TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(canonical_url, content_hash)
);
CREATE INDEX ix_observations_source_time ON source_observations(source_id, retrieved_at DESC);
CREATE INDEX ix_observations_url_time ON source_observations(canonical_url, retrieved_at DESC);
CREATE INDEX ix_observations_hash ON source_observations(content_hash);

CREATE TABLE candidates (
    id TEXT PRIMARY KEY,
    discovered_by_source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
    discovered_from_observation_id TEXT REFERENCES source_observations(id) ON DELETE SET NULL,
    discovered_url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    normalized_title TEXT,
    organizer_name_guess TEXT,
    candidate_type TEXT,
    event_year_guess INTEGER,
    normalized_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new' CHECK(status IN (
        'new','processing','promoted','rejected','duplicate','needs_review','failed'
    )),
    duplicate_of_candidate_id TEXT REFERENCES candidates(id) ON DELETE SET NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    processed_at TEXT,
    rejection_reason TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(canonical_url, normalized_fingerprint)
);
CREATE INDEX ix_candidates_status_seen ON candidates(status, last_seen_at DESC);
CREATE INDEX ix_candidates_fingerprint ON candidates(normalized_fingerprint);

CREATE TABLE programs (
    id TEXT PRIMARY KEY,
    organization_id TEXT REFERENCES organizations(id) ON DELETE SET NULL,
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    category TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    topic_tags_json TEXT NOT NULL DEFAULT '[]',
    geography_json TEXT NOT NULL DEFAULT '[]',
    recurrence_pattern TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(canonical_url, normalized_name)
);
CREATE INDEX ix_programs_normalized_name ON programs(normalized_name);
CREATE INDEX ix_programs_category_active ON programs(category, active);
CREATE INDEX ix_programs_org ON programs(organization_id);

CREATE TABLE editions (
    id TEXT PRIMARY KEY,
    program_id TEXT NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    edition_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    official_url TEXT NOT NULL,
    application_url TEXT,
    event_start_date TEXT,
    event_end_date TEXT,
    event_timezone TEXT,
    event_start_at_utc TEXT,
    event_end_at_utc TEXT,
    format TEXT NOT NULL DEFAULT 'unknown' CHECK(format IN (
        'in_person','online','hybrid','unknown'
    )),
    location_text TEXT,
    country_code TEXT,
    lifecycle_status TEXT NOT NULL DEFAULT 'announced' CHECK(lifecycle_status IN (
        'rumored','announced','applications_open','applications_closed','ongoing',
        'completed','cancelled','unknown'
    )),
    fact_status TEXT NOT NULL DEFAULT 'unverified' CHECK(fact_status IN (
        'confirmed_official','announced_not_open','estimated_recurring','unverified',
        'unknown','conflicting_sources','stale','cancelled_official'
    )),
    application_status TEXT NOT NULL DEFAULT 'unknown' CHECK(application_status IN (
        'not_announced','not_open','open','closed','rolling','unknown','conflicting'
    )),
    fee_min REAL,
    fee_max REAL,
    fee_currency TEXT,
    funding_status TEXT NOT NULL DEFAULT 'unknown' CHECK(funding_status IN (
        'fully_funded','partially_funded','available_competitive','self_funded','unknown','not_applicable'
    )),
    funding_notes TEXT NOT NULL DEFAULT '',
    eligibility_summary TEXT NOT NULL DEFAULT '',
    selection_notes TEXT NOT NULL DEFAULT '',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_verified_at TEXT,
    last_material_change_at TEXT,
    source_fresh_until TEXT,
    user_action TEXT NOT NULL DEFAULT 'monitor' CHECK(user_action IN (
        'apply','prepare','monitor','future_cycle','applied','accepted','rejected','withdrawn','archived'
    )),
    user_notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(program_id, edition_key)
);
CREATE INDEX ix_editions_dates ON editions(event_start_date, event_end_date);
CREATE INDEX ix_editions_lifecycle ON editions(lifecycle_status, application_status);
CREATE INDEX ix_editions_action ON editions(user_action, updated_at DESC);
CREATE INDEX ix_editions_seen ON editions(last_seen_at DESC);
CREATE INDEX ix_editions_program ON editions(program_id);

CREATE TABLE deadlines (
    id TEXT PRIMARY KEY,
    edition_id TEXT NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
    deadline_type TEXT NOT NULL CHECK(deadline_type IN (
        'application_open','application_close','early_application_close','abstract_submission',
        'paper_submission','registration_close','recommendation_letter','travel_grant',
        'scholarship','team_formation','other'
    )),
    label TEXT NOT NULL,
    opens_at_utc TEXT,
    due_at_utc TEXT,
    due_date_local TEXT,
    source_timezone TEXT,
    time_precision TEXT NOT NULL DEFAULT 'unknown' CHECK(time_precision IN (
        'exact_time','date_only','month_only','year_only','unknown'
    )),
    raw_date_text TEXT NOT NULL DEFAULT '',
    fact_status TEXT NOT NULL DEFAULT 'unverified' CHECK(fact_status IN (
        'confirmed_official','announced_not_open','estimated_recurring','unverified',
        'unknown','conflicting_sources','stale','cancelled_official'
    )),
    is_hard_deadline INTEGER NOT NULL DEFAULT 1 CHECK(is_hard_deadline IN (0,1)),
    last_verified_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX ix_deadlines_due ON deadlines(due_at_utc, due_date_local, fact_status);
CREATE INDEX ix_deadlines_edition_type ON deadlines(edition_id, deadline_type);
CREATE INDEX ix_deadlines_status ON deadlines(fact_status, due_date_local);

-- A claim is a proposed or verified value for exactly one entity and one field.
-- Evidence rows are append-oriented; they preserve why the current value was accepted.
CREATE TABLE claims (
    id TEXT PRIMARY KEY,
    program_id TEXT REFERENCES programs(id) ON DELETE CASCADE,
    edition_id TEXT REFERENCES editions(id) ON DELETE CASCADE,
    deadline_id TEXT REFERENCES deadlines(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    proposed_value_json TEXT NOT NULL,
    normalized_value_json TEXT,
    fact_status TEXT NOT NULL DEFAULT 'unverified' CHECK(fact_status IN (
        'confirmed_official','announced_not_open','estimated_recurring','unverified',
        'unknown','conflicting_sources','stale','cancelled_official'
    )),
    source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
    source_observation_id TEXT REFERENCES source_observations(id) ON DELETE SET NULL,
    source_url TEXT NOT NULL,
    source_trust_tier TEXT NOT NULL,
    excerpt TEXT NOT NULL DEFAULT '',
    excerpt_sha256 TEXT,
    extraction_method TEXT NOT NULL CHECK(extraction_method IN (
        'structured_page','rule','llm','manual','feed_metadata'
    )),
    model_name TEXT,
    prompt_version TEXT,
    claim_confidence REAL CHECK(claim_confidence IS NULL OR claim_confidence BETWEEN 0 AND 1),
    verifier_note TEXT NOT NULL DEFAULT '',
    supersedes_claim_id TEXT REFERENCES claims(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    reviewed_at TEXT,
    CHECK ((program_id IS NOT NULL) + (edition_id IS NOT NULL) + (deadline_id IS NOT NULL) = 1)
);
CREATE INDEX ix_claims_program_field ON claims(program_id, field_name, created_at DESC);
CREATE INDEX ix_claims_edition_field ON claims(edition_id, field_name, created_at DESC);
CREATE INDEX ix_claims_deadline_field ON claims(deadline_id, field_name, created_at DESC);
CREATE INDEX ix_claims_status ON claims(fact_status, created_at DESC);
CREATE INDEX ix_claims_observation ON claims(source_observation_id);

CREATE TABLE eligibility_assessments (
    id TEXT PRIMARY KEY,
    edition_id TEXT NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
    profile_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('eligible','possibly_eligible','ineligible','needs_review','future_cycle')),
    blocking_count INTEGER NOT NULL DEFAULT 0,
    unresolved_count INTEGER NOT NULL DEFAULT 0,
    assessment_summary TEXT NOT NULL DEFAULT '',
    criteria_json TEXT NOT NULL DEFAULT '[]',
    assessed_by TEXT NOT NULL CHECK(assessed_by IN ('rules','llm_assisted','manual')),
    model_name TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX ix_eligibility_edition_time ON eligibility_assessments(edition_id, created_at DESC);
CREATE INDEX ix_eligibility_status ON eligibility_assessments(status, created_at DESC);

CREATE TABLE score_snapshots (
    id TEXT PRIMARY KEY,
    edition_id TEXT NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
    scoring_version TEXT NOT NULL,
    fit_score REAL NOT NULL CHECK(fit_score BETWEEN 0 AND 100),
    urgency_score REAL NOT NULL CHECK(urgency_score BETWEEN 0 AND 100),
    priority_band TEXT NOT NULL CHECK(priority_band IN ('critical','high','medium','low','excluded')),
    component_scores_json TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL DEFAULT '[]',
    eligibility_status TEXT NOT NULL,
    deadline_distance_days INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX ix_score_edition_time ON score_snapshots(edition_id, created_at DESC);
CREATE INDEX ix_score_priority_time ON score_snapshots(priority_band, fit_score DESC, urgency_score DESC, created_at DESC);

CREATE TABLE action_items (
    id TEXT PRIMARY KEY,
    edition_id TEXT REFERENCES editions(id) ON DELETE CASCADE,
    deadline_id TEXT REFERENCES deadlines(id) ON DELETE CASCADE,
    action_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    due_at_utc TEXT,
    due_date_local TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','in_progress','done','dismissed','blocked')),
    priority TEXT NOT NULL DEFAULT 'medium' CHECK(priority IN ('critical','high','medium','low')),
    source_claim_id TEXT REFERENCES claims(id) ON DELETE SET NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    CHECK(edition_id IS NOT NULL OR deadline_id IS NOT NULL)
);
CREATE INDEX ix_actions_status_due ON action_items(status, due_at_utc, priority);
CREATE INDEX ix_actions_edition ON action_items(edition_id, status);

CREATE TABLE review_queue (
    id TEXT PRIMARY KEY,
    claim_id TEXT REFERENCES claims(id) ON DELETE CASCADE,
    candidate_id TEXT REFERENCES candidates(id) ON DELETE CASCADE,
    edition_id TEXT REFERENCES editions(id) ON DELETE CASCADE,
    reason_code TEXT NOT NULL,
    priority TEXT NOT NULL CHECK(priority IN ('critical','high','medium','low')),
    state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','accepted','rejected','superseded')),
    title TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    reviewer_notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    reviewed_at TEXT,
    CHECK(claim_id IS NOT NULL OR candidate_id IS NOT NULL OR edition_id IS NOT NULL)
);
CREATE INDEX ix_review_queue_open ON review_queue(state, priority, created_at);

CREATE TABLE notification_log (
    id TEXT PRIMARY KEY,
    channel TEXT NOT NULL CHECK(channel IN ('telegram')),
    notification_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    payload_hash TEXT NOT NULL,
    message_preview TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('pending','sending','sent','failed','suppressed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    telegram_message_id TEXT,
    created_at TEXT NOT NULL,
    last_attempt_at TEXT,
    sent_at TEXT,
    next_retry_at TEXT,
    last_error_redacted TEXT
);
CREATE INDEX ix_notifications_retry ON notification_log(status, next_retry_at, created_at);
CREATE INDEX ix_notifications_entity ON notification_log(entity_type, entity_id, created_at DESC);

CREATE TABLE llm_cache (
    cache_key TEXT PRIMARY KEY,
    backend TEXT NOT NULL,
    model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    input_sha256 TEXT NOT NULL,
    response_json TEXT NOT NULL,
    validation_status TEXT NOT NULL CHECK(validation_status IN ('valid','invalid','review_required')),
    created_at TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    use_count INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX ix_llm_cache_input ON llm_cache(input_sha256, prompt_version);

CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
