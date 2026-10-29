-- Global settings: key/value, value is JSON
CREATE TABLE settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT
);

-- Scan roots
CREATE TABLE scan_roots (
    id           INTEGER PRIMARY KEY,
    path         TEXT NOT NULL,
    path_key     TEXT NOT NULL UNIQUE,
    enabled      INTEGER NOT NULL DEFAULT 1,
    last_scan_at TEXT,
    created_at   TEXT NOT NULL
);

-- File-level information written by the scanner
CREATE TABLE videos (
    id            INTEGER PRIMARY KEY,
    root_id       INTEGER REFERENCES scan_roots(id) ON DELETE SET NULL,
    path          TEXT NOT NULL,
    path_key      TEXT NOT NULL UNIQUE,
    filename      TEXT NOT NULL,
    size_bytes    INTEGER,
    mtime         INTEGER,
    duration_sec  REAL,
    screenshot    TEXT,
    features      TEXT,
    jav_code      TEXT GENERATED ALWAYS AS (json_extract(features, '$.jav_code')) VIRTUAL,
    present       INTEGER NOT NULL DEFAULT 1,
    missing_since TEXT,
    scan_status   TEXT NOT NULL DEFAULT 'pending',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- Unified metadata table
CREATE TABLE metadata (
    id              INTEGER PRIMARY KEY,
    video_id        INTEGER NOT NULL UNIQUE REFERENCES videos(id) ON DELETE CASCADE,
    title           TEXT,
    original_title  TEXT,
    overview        TEXT,
    cover_url       TEXT,
    cover_local     TEXT,
    year            INTEGER,
    release_date    TEXT,
    runtime_sec     INTEGER,
    genres          TEXT,
    tags            TEXT,
    code            TEXT,
    actresses       TEXT,
    studio          TEXT,
    series          TEXT,
    director        TEXT,
    source_name     TEXT,
    matched_by      TEXT,
    raw_payload     TEXT,
    manual_fields   TEXT NOT NULL DEFAULT '[]',
    scrape_status   TEXT NOT NULL DEFAULT 'pending',
    last_scraped_at TEXT,
    version         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- Scrape sources
CREATE TABLE sources (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    enabled      INTEGER NOT NULL DEFAULT 1,
    priority     INTEGER NOT NULL DEFAULT 100,
    version      INTEGER NOT NULL DEFAULT 1,
    config_json  TEXT NOT NULL,
    builtin      INTEGER NOT NULL DEFAULT 0,
    last_test_at TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

-- Async jobs: scan / scrape_batch / scrape_one
CREATE TABLE jobs (
    id               TEXT PRIMARY KEY,
    type             TEXT NOT NULL,
    status           TEXT NOT NULL,
    total            INTEGER NOT NULL DEFAULT 0,
    done             INTEGER NOT NULL DEFAULT 0,
    failed           INTEGER NOT NULL DEFAULT 0,
    payload          TEXT,
    message          TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    started_at       TEXT,
    finished_at      TEXT
);

-- Scrape logs
CREATE TABLE scrape_logs (
    id           INTEGER PRIMARY KEY,
    video_id     INTEGER,
    job_id       TEXT,
    source_name  TEXT,
    feature_used TEXT,
    success      INTEGER,
    message      TEXT,
    created_at   TEXT NOT NULL
);

CREATE INDEX idx_videos_present           ON videos(present);
CREATE INDEX idx_videos_jav_code          ON videos(jav_code);
CREATE INDEX idx_videos_scan_status       ON videos(scan_status);
CREATE INDEX idx_metadata_scrape_status   ON metadata(scrape_status);
CREATE INDEX idx_scrape_logs_video        ON scrape_logs(video_id, created_at);
CREATE INDEX idx_jobs_status              ON jobs(status);
