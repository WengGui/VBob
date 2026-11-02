-- 一部影片可能由多个本地文件组成（A/B 分段、不同清晰度等）。
-- videos 行代表影片分组，video_files 保存实际的播放文件；
-- 旧数据先按一行一个文件回填，重复番号的分组由 Store.merge_duplicate_videos() 合并。
CREATE TABLE video_files (
    id           INTEGER PRIMARY KEY,
    video_id     INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    path         TEXT NOT NULL,
    path_key     TEXT NOT NULL UNIQUE,
    filename     TEXT NOT NULL,
    size_bytes   INTEGER,
    mtime        INTEGER,
    duration_sec REAL,
    present      INTEGER NOT NULL DEFAULT 1,
    missing_since TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE INDEX idx_video_files_video   ON video_files(video_id);
CREATE INDEX idx_video_files_present ON video_files(present);

INSERT INTO video_files(
    video_id, path, path_key, filename, size_bytes, mtime, duration_sec,
    present, missing_since, created_at, updated_at
)
SELECT id, path, path_key, filename, size_bytes, mtime, duration_sec,
       present, missing_since, created_at, updated_at
FROM videos;
