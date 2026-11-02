-- 应用级一次性标记，例如“默认刮削源是否已经写入”。
CREATE TABLE app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
