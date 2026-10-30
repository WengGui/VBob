-- Video favorite flag
ALTER TABLE videos ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0;

-- Metadata extensions
ALTER TABLE metadata ADD COLUMN censored TEXT;        -- censored | uncensored | unknown
ALTER TABLE metadata ADD COLUMN country TEXT;         -- free text
ALTER TABLE metadata ADD COLUMN is_complete INTEGER NOT NULL DEFAULT 0;

-- Scan root scheduling and statistics
ALTER TABLE scan_roots ADD COLUMN scan_interval_minutes INTEGER NOT NULL DEFAULT 0;
ALTER TABLE scan_roots ADD COLUMN last_scan_started_at TEXT;
ALTER TABLE scan_roots ADD COLUMN last_scan_finished_at TEXT;
ALTER TABLE scan_roots ADD COLUMN last_scan_status TEXT DEFAULT 'idle';
ALTER TABLE scan_roots ADD COLUMN last_scan_duration_ms INTEGER;

-- Job ownership for per-directory progress
ALTER TABLE jobs ADD COLUMN root_id INTEGER REFERENCES scan_roots(id) ON DELETE SET NULL;

-- Actresses
CREATE TABLE actresses (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    name_key      TEXT NOT NULL UNIQUE,
    aliases       TEXT NOT NULL DEFAULT '[]',
    birth_date    TEXT,
    nationality   TEXT,
    cover_url     TEXT,
    cover_local   TEXT,
    profile_url   TEXT,
    height_cm     INTEGER,
    bust_cm       INTEGER,
    waist_cm      INTEGER,
    hips_cm       INTEGER,
    cup           TEXT,
    favorite      INTEGER NOT NULL DEFAULT 0,
    is_complete   INTEGER NOT NULL DEFAULT 0,
    source_name   TEXT,
    raw_payload   TEXT,
    manual_fields TEXT NOT NULL DEFAULT '[]',
    version       INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE video_actresses (
    video_id   INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    actress_id INTEGER NOT NULL REFERENCES actresses(id) ON DELETE CASCADE,
    position   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (video_id, actress_id)
);

CREATE INDEX idx_actresses_name_key      ON actresses(name_key);
CREATE INDEX idx_actresses_favorite      ON actresses(favorite);
CREATE INDEX idx_actresses_complete      ON actresses(is_complete);
CREATE INDEX idx_video_actresses_actress ON video_actresses(actress_id);
CREATE INDEX idx_metadata_complete       ON metadata(is_complete);
CREATE INDEX idx_videos_favorite         ON videos(favorite);
CREATE INDEX idx_jobs_root               ON jobs(root_id);
