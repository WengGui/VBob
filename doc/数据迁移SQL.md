# 旧数据适配新版（媒体分类）

适用对象：`D:\software\common\VBob\data\vbob.db`（旧版 0.1.0，结构版本 `0004`）。

## 结论

新版启动时会自动执行 `vbob/migrations/0005_categories.sql`，把旧库升级到带媒体分类的结构，**通常不需要手工改任何数据**。本文 SQL 用于三类场景：

1. 想提前了解迁移会改什么；
2. 无法启动新版时手工升级；
3. 升级后按自己的实际情况调整分类和来源。

> 迁移前请先关闭 VBob，并备份整个 `data` 目录。

```powershell
Copy-Item -Recurse "D:\software\common\VBob\data" "D:\software\common\VBob\data-backup-$(Get-Date -Format yyyyMMdd)"
```

## 当前数据概况（只读检查结果）

| 项目 | 值 |
|------|-----|
| 结构版本 | `0001` ~ `0004` |
| 扫描目录 | 1 个：`\\192.168.2.78\weng_存储空间1\迅雷下载` |
| 刮削源 | 2 个：`javBus`（番号源）、`javBusActress`（演员源） |
| 视频 | 747 条（其中 569 条文件仍存在） |
| 有番号 | 400 条 |
| 有剧集键 | 7 条 |
| 既无番号也无剧集 | 340 条（多为 `VID_2024...mp4` 这类手机视频，也有少量中文名 rmvb） |
| 已刮削 | 496 条，来源均为 `javBus` |

## 一、自动迁移的内容（0005）

新版首次启动时会执行下面这段 SQL。**不需要手工执行**，列在这里是为了对照和排查。

```sql
BEGIN IMMEDIATE;

ALTER TABLE sources ADD COLUMN category TEXT NOT NULL DEFAULT 'other';
UPDATE sources SET category = 'jav';

ALTER TABLE scan_roots ADD COLUMN category TEXT NOT NULL DEFAULT 'other';
ALTER TABLE scan_roots ADD COLUMN source_ids TEXT NOT NULL DEFAULT '[]';
UPDATE scan_roots SET category = 'jav';

ALTER TABLE videos ADD COLUMN category TEXT NOT NULL DEFAULT 'other';
ALTER TABLE videos ADD COLUMN category_manual INTEGER NOT NULL DEFAULT 0;
UPDATE videos SET category = COALESCE(
    (SELECT category FROM scan_roots WHERE scan_roots.id = videos.root_id), 'jav'
);

ALTER TABLE metadata ADD COLUMN source_id INTEGER;
ALTER TABLE metadata ADD COLUMN source_names TEXT NOT NULL DEFAULT '[]';

CREATE INDEX idx_videos_category ON videos(category);

INSERT INTO schema_migrations(version, applied_at) VALUES ('0005', datetime('now'));
COMMIT;
```

迁移后你这套数据会变成：

- `javBus`、`javBusActress` → 媒体类型 `jav`；
- 扫描目录 → `jav`，限定源为空（表示沿用该类型下全部启用源）；
- 747 条视频 → 全部 `jav`，`category_manual = 0`；
- 已刮削记录的 `source_name` 保留，`source_names` 为空数组，详情页会回退显示 `source_name`；
- 播放器、扫描等设置不变。

> ⚠️ 如果手工执行上面的 SQL，必须连同最后的 `INSERT INTO schema_migrations` 一起执行，否则下次启动会重复建列并报错。已经升级过的库不要再执行。

### 1.1 后续版本还会自动执行 0006

当前版本启动时还会执行 `0006_source_probe.sql`：

```sql
ALTER TABLE sources ADD COLUMN last_test_result_json TEXT;
```

它只为每个源保存最近一次连通性检测结果（信号格数、耗时、状态码），不改动任何旧数据。用新版启动一次即可，无需手工执行。

### 1.2 自动备份

从带自动备份的版本开始，启动时检测到有待应用迁移，会先把数据库复制到 `data/backups/vbob-<时间>.db`，最多保留 5 份。这层备份与手工备份互为补充；升级失败时优先用自动备份或你提前复制的整个 `data` 目录恢复。

## 二、可选：按实际情况修正分类

以下 SQL 都在**自动迁移之后**执行。先在 SQLite 工具里运行查询确认结果，再执行 UPDATE。

### 2.1 把未识别番号/剧集的视频归到「其他」

预览：

```sql
SELECT id, filename
FROM videos
WHERE json_extract(features, '$.jav_code') IS NULL
  AND json_extract(features, '$.episode_key') IS NULL
ORDER BY filename;
```

确认后执行：

```sql
UPDATE videos
SET category = 'other',
    category_manual = 1
WHERE json_extract(features, '$.jav_code') IS NULL
  AND json_extract(features, '$.episode_key') IS NULL;
```

说明：

- `category_manual = 1` 表示这是手动分类，之后修改目录分类不会覆盖它；
- 这 340 条里可能混有电影或动漫，执行前建议先看一遍文件名，必要时把条件改得更精确，例如只处理 `filename LIKE 'VID_%'`：

```sql
UPDATE videos
SET category = 'other', category_manual = 1
WHERE filename LIKE 'VID_%';
```

### 2.2 修改目录分类

```sql
-- 查看当前目录
SELECT id, path, category, source_ids FROM scan_roots;

-- 例：把 1 号目录改成「其他」
UPDATE scan_roots SET category = 'other' WHERE id = 1;

-- 同步目录下未被手动分类的视频
UPDATE videos
SET category = 'other'
WHERE root_id = 1 AND category_manual = 0;
```

### 2.3 回填来源列表

旧数据只有单个 `source_name`，回填后详情页会把它显示为来源列表：

```sql
UPDATE metadata
SET source_names = json_array(source_name)
WHERE source_name IS NOT NULL
  AND source_name <> ''
  AND (source_names IS NULL OR source_names = '[]');
```

### 2.4 目录限定源（可选）

`source_ids` 是 JSON 数组，按数组顺序执行。空数组表示使用该分类下全部启用源。

```sql
-- 查看源 ID
SELECT id, name, category, enabled FROM sources ORDER BY priority;

-- 例：1 号目录只按顺序使用 2、3 号源
UPDATE scan_roots
SET source_ids = json_array(2, 3)
WHERE id = 1;

-- 恢复自动（清空限定）
UPDATE scan_roots SET source_ids = '[]' WHERE id = 1;
```

### 2.5 非 JAV 源要同时改列和 JSON

`category` 既存于 `sources` 表列，也存于 `config_json`。手工修改时必须两处一起改，否则在界面里编辑保存时会被旧值覆盖。

```sql
-- 例：把名为 TMDB 开头的源改成「电影」
UPDATE sources
SET category = 'movie',
    config_json = json_set(config_json, '$.category', 'movie')
WHERE name LIKE 'TMDB%';
```

媒体类型取值：`movie` / `anime` / `series` / `jav` / `other`。

### 2.6 视频单独改分类

```sql
-- 把指定视频改成动漫，并标记为手动分类
UPDATE videos
SET category = 'anime', category_manual = 1
WHERE id = 123;
```

新版界面里也可以直接在「编辑视频 → 媒体类型」中修改，效果相同。

## 三、验证

```sql
-- 结构版本应包含 0005、0006（以当前发布版本为准）
SELECT version FROM schema_migrations ORDER BY version;

-- 新列是否存在
PRAGMA table_info(videos);     -- category, category_manual
PRAGMA table_info(metadata);   -- source_id, source_names

-- 分类分布
SELECT category, COUNT(*) FROM videos GROUP BY category;

-- 源与目录
SELECT id, name, category FROM sources;
SELECT id, path, category, source_ids FROM scan_roots;
```

预期结果（未执行可选修正时）：

```text
videos:   jav 747
sources:  javBus=jav, javBusActress=jav
roots:    category=jav, source_ids=[]
```

## 四、执行方式

**推荐：直接启动新版**

用新版 `VBob.exe` 指向旧数据目录即可自动迁移，不需要执行任何 SQL：

```powershell
VBob.exe --data-dir "D:\software\common\VBob\data"
```

或者把新版 exe 放到 `D:\software\common\VBob`，保持 `data` 目录不变，双击运行。

**手工执行（不推荐）**

- 用 DB Browser for SQLite 打开 `vbob.db`，关闭程序后执行 SQL；
- 或用 Python：

```bash
# 先把要执行的 SQL 保存为 migrate.sql
python -c "import sqlite3;c=sqlite3.connect(r'D:\software\common\VBob\data\vbob.db');c.executescript(open(r'migrate.sql',encoding='utf-8').read());c.commit();c.close()"
```

手工执行时注意：

1. 先确认 `schema_migrations` 里没有 `0005`；
2. 结构迁移和版本记录必须在同一个事务里；
3. 程序运行期间不要直接改库（SQLite 会锁冲突）。

## 五、回滚

迁移只增加列和索引，不删除数据。如需回滚：

1. 关闭程序；
2. 用备份的 `data` 目录覆盖回去。

单独删除新增列也可以，但 SQLite 对 `DROP COLUMN` 有限制，建议直接用备份恢复。

## 六、常见问题

**升级后菜单里全是 JAV，看不到「其他」？**

「其他」只显示 `category='other'` 的视频。旧数据默认全部归为 `jav`，需要按 2.1 把无番号视频改为 `other`。

**原来的刮削来源不显示了？**

详情页优先读 `source_names`，为空时回退 `source_name`。如果显示异常，执行 2.3 回填。

**目录里既有 JAV 又有电影怎么办？**

目录只能有一个默认分类。建议给电影/动漫单独建目录并设置对应分类；同一目录内的个别视频可以在「编辑视频」里单独修改分类。
