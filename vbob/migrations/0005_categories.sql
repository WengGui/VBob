-- 媒体类型：源、目录、视频共用 movie/anime/series/jav/other。
-- 升级前的数据都以 JAV 为主，这里把已有源、目录和视频统一归为 jav，保持原有刮削行为。

ALTER TABLE sources ADD COLUMN category TEXT NOT NULL DEFAULT 'other';
UPDATE sources SET category = 'jav';

ALTER TABLE scan_roots ADD COLUMN category TEXT NOT NULL DEFAULT 'other';
-- 目录限定源：按用户勾选顺序保存的源 ID 数组，空数组表示该分类下全部启用源。
ALTER TABLE scan_roots ADD COLUMN source_ids TEXT NOT NULL DEFAULT '[]';
UPDATE scan_roots SET category = 'jav';

ALTER TABLE videos ADD COLUMN category TEXT NOT NULL DEFAULT 'other';
-- 1 表示用户手动改过分类，目录改分类时不再覆盖。
ALTER TABLE videos ADD COLUMN category_manual INTEGER NOT NULL DEFAULT 0;
UPDATE videos SET category = COALESCE(
    (SELECT category FROM scan_roots WHERE scan_roots.id = videos.root_id), 'jav'
);

-- 视频记住的偏好源（详情页切换后持久化）与本次贡献数据的源列表。
ALTER TABLE metadata ADD COLUMN source_id INTEGER;
ALTER TABLE metadata ADD COLUMN source_names TEXT NOT NULL DEFAULT '[]';

CREATE INDEX idx_videos_category ON videos(category);
