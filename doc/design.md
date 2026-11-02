# 本地视频管理刮削系统 — 设计文档

> 版本 v0.5（2026-10-29，新增演员体系、完整度、收藏与设置重构；变更摘要见第 13 节，增量需求见第 14 节）

## 1. 项目概述

### 1.1 定位

一个轻量级的本地视频管理工具，核心能力是**扫描本地视频文件、通过用户可配置的刮削源获取元数据、在 Web 页面管理元数据、并调起本地播放器播放**。

不内置流媒体/转码服务，播放交给用户本地的 mpv / PotPlayer / VLC 等播放器。

### 1.2 核心设计原则

1. **一个文件库，一套元数据模型**。不为不同类型视频建立隔离的库。
2. **番号只是一种可提取特征**，与标题、年份、季集标记平级，不构成独立子系统。
3. **所有刮削源均可配置**，内置源与用户自定义源走同一接口。
4. **按特征路由，失败可降级**：番号源失败自动降级到通用源，用户无感知。
5. **播放由后端直接调起本地播放器**：前端只传 `video_id`，不接触文件路径，也不直连本地端口。
6. **以完整度衡量刮削质量**：必填字段缺失不会让刮削失败，而是标记为不完整并允许手动补齐。
7. **演员是一等实体**：演员拥有独立资料、海报墙、收藏和刮削源；视频与演员是多对多关系。

### 1.3 非目标

- 不做视频转码、不做流媒体推流。
- 不做多用户权限体系（单用户本地工具）。
- 不做 Docker/远程/多设备部署，只支持单机本地运行。
- 不做磁力下载；不做厂商聚合浏览页（演员页与收藏已纳入 v0.5）。

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                  Web 前端 (React)                        │
│   海报墙 · 详情侧边栏 · 元数据编辑 · 源配置 · 设置         │
└───────────────────────┬─────────────────────────────────┘
                        │ HTTP REST + SSE
┌───────────────────────▼─────────────────────────────────┐
│                 后端服务 (Python / FastAPI)               │
│                                                          │
│  ┌────────────┐  ┌──────────────┐  ┌─────────────────┐  │
│  │ 文件扫描器  │→ │ 特征提取管道  │→ │  刮削调度器      │  │
│  │ Scanner    │  │ Extractor    │  │  ScrapeDispatcher│ │
│  └────────────┘  └──────────────┘  └────────┬────────┘  │
│                                             │            │
│  ┌────────────┐  ┌──────────────┐  ┌───────▼─────────┐  │
│  │ 元数据存储  │  │ 设置/任务管理  │  │  源执行器        │  │
│  │ SQLite     │  │ Settings/Jobs │  │  SourceRunner   │  │
│  └────────────┘  └──────────────┘  └─────────────────┘  │
│  ┌────────────────────────────────────────────────────┐  │
│  │ 播放器调用 PlayerLauncher：exec 本地播放器          │  │
│  └────────────────────────────────────────────────────┘  │
└───────────────────────┬─────────────────────────────────┘
                        │ exec（参数数组）
                        ▼
            本地播放器 mpv / VLC / PotPlayer ...
```

### 2.1 运行形态

- **单机、单进程**：后端内置前端静态资源与 SQLite，直接在本机运行；浏览器访问 `127.0.0.1:8080`。
- 媒体文件、数据库、播放器都在同一台机器，播放时不需要任何路径转换，也不涉及远程或多设备访问。
- 支持 Windows/macOS/Linux 桌面环境；可选开机自启、启动后自动打开浏览器。

### 2.2 播放链路

前端不直接调起播放器，也不访问任何本地端口：

```
前端 POST /api/videos/{id}/play {file_id?, player?, seek?}
        │
        ▼
后端 PlayerLauncher
  1. 按 video_id + 可选 file_id 取出文件路径；分组包含多个可用文件时返回
     `multiple_files`，由前端弹出文件选择框
  2. 校验路径位于已配置的扫描根目录内
  3. 解析播放器（设置指定 > 自动探测 mpv/VLC/PotPlayer）
  4. exec.Command(player, args...)，返回 pid
        │
        ▼
   本地播放器
```

- 前端只传 `video_id`、可选的 `file_id` 与播放器/起播位置，**永远不传文件路径**。
- 播放器调用使用参数数组，不经 shell；文件路径作为独立参数传入。
- 播放器配置：设置项 `playback.player`（名称、可执行文件路径、附加参数模板）；未配置时按平台在 `PATH` 与常见安装目录中探测。
- 播放失败返回明确原因码（`no_player` / `player_not_found` / `path_not_found` / `path_outside_root`），前端直接展示。
- 后端不跟踪播放进度；每次播放都是一次独立的进程启动。第二版可通过播放器 IPC（如 mpv JSON IPC）实现"继续观看"。

### 2.3 端口

- 后端默认监听 `127.0.0.1:8080`，端口可配置。
- 本工具定位单机使用，第一版不提供鉴权；不要将监听地址改为对外地址。启动时若检测到非回环绑定，打印醒目警告。

---

## 3. 数据模型

### 3.1 表结构

```sql
-- 全局设置：key/value，value 为 JSON
CREATE TABLE settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMP
);

-- 扫描根目录
CREATE TABLE scan_roots (
    id          INTEGER PRIMARY KEY,
    path        TEXT NOT NULL,              -- 绝对路径
    path_key    TEXT NOT NULL UNIQUE,       -- 归一化 + 大小写折叠
    enabled     INTEGER DEFAULT 1,
    last_scan_at TIMESTAMP,
    created_at  TIMESTAMP
);

-- 影片分组：扫描阶段写入，与刮削无关。
-- 同一目录下番号相同的多个文件（A/B 分段、不同清晰度等）共享一行；
-- path/filename 等主文件字段指向当前优先播放的文件。
CREATE TABLE videos (
    id            INTEGER PRIMARY KEY,
    root_id       INTEGER REFERENCES scan_roots(id) ON DELETE SET NULL,
    path          TEXT NOT NULL,            -- 主文件归一化绝对路径（展示用）
    path_key      TEXT NOT NULL UNIQUE,     -- 主文件归一化 + 大小写折叠
    filename      TEXT NOT NULL,
    size_bytes    INTEGER,
    mtime         INTEGER,                  -- 文件修改时间（秒），增量扫描依据
    duration_sec  REAL,                     -- 文件本身时长（ffprobe，可空）
    screenshot    TEXT,                     -- 本地截图相对路径
    features      TEXT,                     -- JSON: 提取出的特征字典
    jav_code      TEXT GENERATED ALWAYS AS (json_extract(features, '$.jav_code')) VIRTUAL,
    present       INTEGER DEFAULT 1,        -- 0 = 分组内所有文件均缺失
    missing_since TIMESTAMP,
    scan_status   TEXT DEFAULT 'pending',   -- pending/scanned/error
    created_at    TIMESTAMP,
    updated_at    TIMESTAMP
);

-- 实际播放文件：一部影片可以包含多个文件
CREATE TABLE video_files (
    id            INTEGER PRIMARY KEY,
    video_id      INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    path          TEXT NOT NULL,
    path_key      TEXT NOT NULL UNIQUE,
    filename      TEXT NOT NULL,
    size_bytes    INTEGER,
    mtime         INTEGER,
    duration_sec  REAL,
    present       INTEGER DEFAULT 1,
    missing_since TIMESTAMP,
    created_at    TIMESTAMP,
    updated_at    TIMESTAMP
);

-- 统一元数据表：通用字段 + 可选扩展字段
CREATE TABLE metadata (
    id              INTEGER PRIMARY KEY,
    video_id        INTEGER NOT NULL UNIQUE REFERENCES videos(id) ON DELETE CASCADE,
    title           TEXT,
    original_title  TEXT,
    overview        TEXT,
    cover_url       TEXT,
    cover_local     TEXT,                   -- 本地缓存相对路径
    year            INTEGER,
    release_date    TEXT,
    runtime_sec     INTEGER,                -- 站点标注时长，与 videos.duration_sec 不同
    genres          TEXT,                   -- JSON array
    tags            TEXT,                   -- JSON array
    -- 扩展字段（番号/影视通用，均可为空）
    code            TEXT,                   -- 番号，如 SSIS-001
    actresses       TEXT,                   -- JSON array
    studio          TEXT,                   -- 厂商/制作公司
    series          TEXT,                   -- 系列
    director        TEXT,
    -- 来源与状态
    source_name     TEXT,
    matched_by      TEXT,                   -- jav_code / title / ...
    raw_payload     TEXT,                   -- 源原始返回，便于调试
    manual_fields   TEXT DEFAULT '[]',      -- JSON array：用户手动改过的字段名
    scrape_status   TEXT DEFAULT 'pending', -- pending/success/failed/no_match/skipped_manual
    last_scraped_at TIMESTAMP,
    version         INTEGER NOT NULL DEFAULT 1,  -- 乐观锁
    created_at      TIMESTAMP,
    updated_at      TIMESTAMP
);

-- 源配置
CREATE TABLE sources (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    enabled       INTEGER DEFAULT 1,
    priority      INTEGER DEFAULT 100,      -- 数值越小越先尝试
    version       INTEGER DEFAULT 1,        -- 配置版本，缓存失效依据
    config_json   TEXT NOT NULL,            -- 完整源配置（见第 6 节）
    builtin       INTEGER DEFAULT 0,
    last_test_at  TIMESTAMP,
    created_at    TIMESTAMP,
    updated_at    TIMESTAMP
);

-- 异步任务：扫描、批量刮削、单文件刮削
CREATE TABLE jobs (
    id          TEXT PRIMARY KEY,           -- uuid
    type        TEXT NOT NULL,              -- scan / scrape_batch / scrape_one
    status      TEXT NOT NULL,              -- queued/running/succeeded/failed/canceled
    total       INTEGER DEFAULT 0,
    done        INTEGER DEFAULT 0,
    failed      INTEGER DEFAULT 0,
    payload     TEXT,                       -- JSON 入参
    message     TEXT,
    created_at  TIMESTAMP,
    started_at  TIMESTAMP,
    finished_at TIMESTAMP
);

-- 刮削日志
CREATE TABLE scrape_logs (
    id            INTEGER PRIMARY KEY,
    video_id      INTEGER,
    job_id        TEXT,
    source_name   TEXT,
    feature_used  TEXT,
    success       INTEGER,
    message       TEXT,
    created_at    TIMESTAMP
);
```

### 3.2 索引、PRAGMA 与迁移

```sql
CREATE INDEX idx_videos_present        ON videos(present);
CREATE INDEX idx_video_files_video     ON video_files(video_id);
CREATE INDEX idx_videos_jav_code       ON videos(jav_code);
CREATE INDEX idx_videos_scan_status    ON videos(scan_status);
CREATE INDEX idx_metadata_scrape_status ON metadata(scrape_status);
CREATE INDEX idx_scrape_logs_video     ON scrape_logs(video_id, created_at);
CREATE INDEX idx_jobs_status           ON jobs(status);
```

- 连接初始化：`PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;`
- 依赖 SQLite 3.31+ 的生成列与 JSON1；选用自带较新 SQLite 的驱动。
- 所有 schema 变更以版本化 SQL 文件存放（`migrations/000N_xxx.sql`），启动时自动迁移，记录在 `schema_migrations` 表。
- 数据目录布局：

```
data/
  vbob.db
  covers/{video_id}.jpg
  screenshots/{video_id}.jpg
  logs/
```

### 3.3 设计说明

- **路径与去重**：`path` 是展示用的规范化绝对路径；`path_key` 为 `Clean` 后按平台规则折叠大小写（Windows/macOS 折叠，Linux 不折叠）的结果，`UNIQUE(path_key)` 防止同一文件在大小写不敏感文件系统上重复入库。不跟随符号链接，避免循环与重复。
- **文件失效**：扫描发现文件不存在时将 `present=0` 并记录 `missing_since`，不立即删除元数据；用户在界面上确认后清理，或配置为 N 天后自动清理。
- **特征查询**：`jav_code` 为 `features` 的生成列并建索引，筛选按番号走 SQL，不在应用层内存过滤。
- **`scan_status` 与 `scrape_status` 分离**：前者描述文件扫描，后者描述刮削结果（成功/失败/无匹配/因手动字段跳过）。
- **`manual_fields` 替代单一 `manual_edited`**：按字段记录用户覆盖，自动刮削只更新不在其中的字段；`version` 用于处理后台刮削与手动编辑的并发。
- **时长语义**：`videos.duration_sec` 是文件真实时长（ffprobe），`metadata.runtime_sec` 是站点标注时长，两者可能不同，前端分别使用。
- **来源追踪**：默认"先到先得"，`source_name`/`matched_by` 记录最终采纳的源；自动刮削只覆盖非手动字段，因此不同源的结果具备互补性。
- **`raw_payload` 保留策略**：默认只保留最近一次，设置项可关闭；数据库提供备份/导出入口。

---

## 4. 文件扫描与库同步

### 4.1 扫描流程

扫描是异步任务（`jobs.type=scan`），由 `POST /api/scans` 触发，前端通过 SSE 或轮询获取进度，可取消。

1. 遍历每个启用的 `scan_roots`（使用 `os.walk`，不跟随符号链接），规则见 4.2。
2. 对每个候选文件计算 `path_key`、`size_bytes`、`mtime`。
3. 已存在且 `size_bytes` + `mtime` 未变化 → 跳过（增量扫描）；变化或新增 → 进入特征提取。
4. 本轮未出现的已入库文件 → `present=0`。
5. 时长与截图可选地交给探测队列（ffprobe），失败不阻塞扫描。
6. 任务结束写入统计（总数/新增/更新/缺失/失败）。

### 4.2 扫描规则

- 扩展名白名单可配置，默认：`mp4 mkv avi wmv mov ts m2ts mpg mpeg flv webm rmvb m4v`。
- 忽略规则：隐藏文件与目录、`$RECYCLE.BIN`、`System Volume Information`、`@eaDir`、可配置的 glob（如 `*sample*`、`*trailer*`）。
- 最小文件大小可配置（默认 50MB），过滤样片与缩略图。
- 目录权限错误记录警告并继续，不中断整个任务。
- 默认不跟随符号链接；嵌套的扫描根目录会被检测并提示，避免重复入库。

### 4.3 媒体探测

- 使用外部 `ffprobe`（可选依赖）读取时长；未安装时 `duration_sec` 为空，其余功能不受影响。
- 截图由 `ffmpeg` 在播放进度约 10% 处截取一帧，仅在无封面时使用；生成失败不阻塞刮削。
- 探测任务与刮削共用工作池但有独立优先级，避免大库扫描阻塞用户操作。

### 4.4 缺失文件处理

- `present=0` 的记录在海报墙默认隐藏，可切换到"缺失"视图查看。
- 提供 `DELETE /api/videos/{id}`（仅元数据）与批量清理接口；默认不自动删除文件。
- 文件移动/改名后，若新路径出现在同一扫描根中会作为新记录入库；按 `size+mtime` 做重复提示（去重合并留到第二版）。

---

## 5. 特征提取管道

### 5.1 提取器接口

```python
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class FileRef:
    filename: str      # 文件名（含扩展名）
    rel_path: str      # 相对扫描根的路径
    dirs: tuple[str, ...]  # 从近到远的目录名，用于回退匹配（如番号在文件夹上）

class FeatureExtractor(Protocol):
    name: str
    def extract(self, file: FileRef) -> dict[str, object]: ...
```

- 所有提取器输出合并为 `features` 字典，键名以提取器命名空间区分，避免冲突。
- 提取器内部失败静默跳过，不阻塞其他提取器。
- 匹配顺序：先文件名，再由近到远的目录名；文件名命中后不再依赖目录。

### 5.2 文件名清洗

- 剥离分辨率标记（`1080p`/`4K`/`2160p`）、编码（`h264`/`x265`/`HEVC`）、站点水印、语言标记（`[中字]`/`-C`/`_CHS`）、发布组方括号内容。
- 清洗规则以正则列表形式存于设置（`scraping.clean_rules`），可增删；非法正则保存时校验并拒绝。
- 清洗只用于提取，原始文件名始终保留在 `videos.filename`。

### 5.3 番号提取与归一化

按类型识别，输出 `jav_code`（展示形式）、`jav_family`、`jav_match_key`（比较键）：

| 类型 | 示例 | 匹配规则（要点） |
|------|------|------------------|
| 标准有码 | `SSIS-001`、`ABP-123` | `(?i)\b[A-Z]{2,6}-\d{2,5}\b` |
| 无码 | `123456-789`、`HEYZO-1234` | `\b\d{6}-\d{3}\b`、`(?i)HEYZO-?\d{3,4}` |
| FC2 | `FC2-1234567`、`FC2-PPV-1234567` | `(?i)FC2[-_ ]?(PPV[-_ ]?)?\d{6,8}` |
| 素人 | 按配置前缀 | 用户可配置正则 |

- **归一化按族定义，不全局补零**：标准番号保留原始位数（源站通常同时接受 `SSIS-1` 与 `SSIS-001`）；比较键为"字母部分 + 数字去前导零"，如 `SSIS-001` → `SSIS|1`；FC2/HEYZO/无码各自定义比较键。
- **防误匹配**：使用词边界；维护停用词表（`PART-01`、`CD-02`、`VOL-3` 等常见误中模式）作为黑名单，可配置。
- 输出示例：`{"jav_code":"SSIS-001","jav_family":"standard","jav_match_key":"SSIS|1"}`。

### 5.4 标题与年份提取

1. 同样先清洗干扰词。
2. 年份：匹配 `(19|20)\d{2}`，限制在 `1950..当前年+2`，优先取靠后的独立词元。
3. 标题：清洗后去掉年份、扩展名、代码段，剩余部分作为候选标题。
4. 输出 `{"title": "...", "year": 2023}`；对无法可靠解析的文件只输出空标题，交由 query 源跳过。

### 5.5 手动修正特征

- 详情页提供"特征编辑"入口，可修改 `jav_code` 与 `title/year`；保存后触发重新刮削（异步入队）。
- 修改会写入 `manual_fields`（当前版本仅 `jav_code`、`title`、`year` 三个键），后续自动刮削不再覆盖这些特征值。
- 第一版即支持该功能（初稿放在第二版，已前移——错误匹配的兜底必须可用）。

### 5.6 季集提取（第二版）

- 匹配 `S01E02`、`第2季第3集`、`EP03` 等，输出 `{"season":1,"episode":2}`，参与 `query` 源占位符与详情展示。

---

## 6. 源配置格式

### 6.1 统一 Schema（YAML）

```yaml
name: "javbus"                    # 唯一标识
enabled: true
priority: 10                      # 越小越先尝试
type: "feature"                   # feature | query
feature: "jav_code"               # feature 类型声明匹配的特征键

request:
  url: "https://www.javbus.com/{jav_code}"
  method: "GET"                   # GET | POST
  headers:
    User-Agent: "Mozilla/5.0 ..."
  cookies: ""                     # 可选，反爬用
  proxy: ""                       # 可选，http/socks5
  timeout_ms: 8000
  encoding: "auto"                # auto | utf-8 | gbk | euc-jp | shift_jis
  rate_limit:                     # 按目标站点（host）限流
    qps: 1
    burst: 2
  retry:
    max: 2
    backoff_ms: 500

extract:
  title:        "xpath: //h3/text()"
  cover_url:    "css: .bigImage img@src"
  actresses:    "css: .star-name a@text | array"
  studio:       "css: .info a[href*=studio]@text"
  release_date: "xpath: //span[contains(text(),'發行日期')]/following-sibling::span/text()"
  code:         "regex: [A-Z]+-\\d+"

asset_base_url: ""                # 可选：相对封面/资源 URL 的补全前缀
validators:
  - field: "title"
    required: true
deny_title_patterns:              # 可选，覆盖内置错误页特征
  - "404"
  - "Not Found"
  - "検索結果"
```

### 6.2 提取器方言（明确支持范围）

| 前缀 | 语义 | 实现建议 |
|------|------|---------|
| `css:` | CSS 选择器子集，可选 `@attr`，缺省取文本 | `parsel`（底层 lxml/cssselect）；**不支持 `:contains()` 等 jQuery 扩展** |
| `xpath:` | XPath 1.0 表达式 | `parsel`/`lxml`；需要按文本匹配时优先用它 |
| `json:` | JMESPath 表达式（如 `results[0].title`） | `jmespath`，用于 API 源 |
| `regex:` | 对原始响应文本做正则，取第 1 个捕获组 | 兜底 |

- 选择器匹配多个元素时：标量字段取第一个；`| array` 后缀取全部。
- 文本结果统一做 HTML 实体解码与首尾空白裁剪。
- 相对 `src`/`href` 按**重定向后的响应 URL** 解析为绝对地址；仍为相对时再拼 `asset_base_url`。
- 不支持的选择器语法在保存时通过测试接口直接报错，避免运行期静默失败。

### 6.3 占位符与编码

- 占位符直接使用特征键名：`{jav_code}`、`{title}`、`{year}`、`{season}` 等；不再使用 `{code}` 别名，避免映射歧义。
- 替换值按 URL 组件规则进行百分号编码；值为空且该源必需时，跳过该源。
- 请求体（POST）支持 `application/x-www-form-urlencoded` 与 JSON 两种模板。

### 6.4 响应编码

- `encoding: auto` 时先看 HTTP `Content-Type`，再嗅探 HTML `<meta charset>` 与 BOM，用 `charset-normalizer` 或 `bs4.dammit` 转码为 UTF-8。
- 覆盖 CJK 站点常见的 GBK/GB18030、EUC-JP、Shift_JIS；无法识别时按 UTF-8 尝试并记录警告。

### 6.5 匹配校验

`Valid()` 不只看 title 非空，默认规则：

- HTTP 2xx；非 2xx 直接失败。
- 必填字段（`validators.required`）非空。
- **feature 源回验**：返回的番号与请求番号按 `jav_match_key` 比较，不一致视为错误匹配，记录日志并继续下一个源。
- **query 源相似度**：候选标题与输入标题的归一化相似度 ≥ `0.6`（可配），若输入带年份则返回年份需一致或为空。
- 错误页检测：标题包含 `404`/`Not Found`/`検索結果`/`エラー` 等模式时判失败；可在源配置中扩展。
- query 源返回多条结果时，取第一条通过相似度校验的结果。

### 6.6 内置源与用户源

- 内置源：随程序分发，`builtin=1`；用户可禁用、可调优先级，不可编辑 `request`/`extract`。
- 用户源：`builtin=0`，可自由编辑删除。
- 升级策略：按 `name` 匹配，保留用户 `enabled`/`priority`，替换其余字段并递增 `version`。

### 6.7 密钥与秘密

- 源的 API key 等秘密不写入共享配置，使用 `{{secret:tmdb_api_key}}` 占位，从设置或环境变量解析。
- 第一版内置两个源：`javbus`/`javdb` 之一（feature）+ TMDB（query，需用户在设置页填写 key）。

### 6.8 源测试

- `POST /api/sources/test`：传入配置与一组测试特征，返回请求 URL、HTTP 状态、耗时、提取结果与校验结论。
- MVP 提供 CLI 子命令 `vbob source test -c source.yaml -f jav_code=SSIS-001`，在无 Web 编辑器的阶段也能高效调试源。

---

## 7. 刮削调度器

### 7.1 调度流程

```
输入: video（含 features），参数 {force, overwrite_manual}
输出: metadata | error

1. 读取现有 metadata。
   若 !force 且待填字段全部在 manual_fields 中：
       scrape_status=skipped_manual，直接返回。

2. 加载所有 enabled 源，按 priority 升序（同优先级按 name 稳定排序）。

3. 第一轮：feature 类型源
   for src in sources where src.type == feature:
       若 src.feature 不在 features 中 → 跳过
       result = src.Execute()
       若校验失败（含番号回验不符）→ 记日志，继续
       若通过 → 合并保存，返回 success

4. 第二轮：query 类型源（降级）
   for src in sources where src.type == query:
       若 features.title 为空 → 跳过
       result = src.Execute()
       若校验失败（含标题相似度不足）→ 继续
       若通过 → 合并保存，返回 success

5. 全部失败：
   若存在网络/源执行错误 → scrape_status=failed
   否则 → scrape_status=no_match
   写 scrape_logs 并返回 ErrNoMatch。
```

**优先级语义（明确）**：类型轮次优先于 `priority`。即使某个 query 源的 `priority` 数值小于某个 feature 源，feature 轮也先执行。`priority` 只在同一轮内生效。

### 7.2 结果合并

- 新结果逐字段写入：若字段在 `manual_fields` 中且未指定 `overwrite_manual` → 保留用户值；否则用源结果覆盖。
- 新结果没有提供的字段保留原值，不清空。
- 每次写入递增 `metadata.version`；写入前比对读取时的版本，冲突则重新读取并重试一次，仍冲突则记录失败（避免覆盖用户并发编辑）。
- `source_name`、`matched_by`、`raw_payload` 随本次结果更新。

### 7.3 并发、限流与重试

- 视频维度并发，默认工作池 3；同一视频内部按源顺序串行，保证优先级语义。
- **按源站 host 做令牌桶限流**（`request.rate_limit`），跨视频共享，避免并发 3 时集中冲击同一站点。
- 每个源独立 `timeout_ms` 与 `retry.max/backoff_ms`；仅对网络错误与 5xx 重试，4xx 不重试。
- 第二版增加按源的失败冷却（熔断）与健康统计。

### 7.4 缓存

- 正缓存：键为 `source_name + source.version + match_key`（番号用 `jav_match_key`，query 用归一化标题+年份），默认 TTL 10 分钟，LRU 容量有上限。
- 负缓存：失败结果缓存 60 秒，避免批量刮削反复冲击同一个坏源。
- 源配置更新（`version` 变化）后旧缓存自然失效。

### 7.5 重新刮削与手动编辑

- 单文件：`POST /api/videos/{id}/scrape`，参数 `{force: bool, overwrite_manual: bool}`。
  - `force=false`：只补非手动字段；
  - `force=true`：重跑，仍保留手动字段；
  - `overwrite_manual=true`：连手动字段一起覆盖（前端需二次确认）。
- 批量：只处理 `present=1` 的视频；默认跳过"全部字段均为手动"的记录，界面提供"覆盖手动编辑"开关。
- `PATCH /api/videos/{id}/features` 保存成功后默认异步入队重刮（可在请求中关闭）。

### 7.6 状态写入

- 开始刮削置 `scrape_status=scraping`（新增枚举值），结束置 `success`/`failed`/`no_match`/`skipped_manual`。
- 元数据更新与状态更新在同一事务内完成。

---

## 8. API 设计

### 8.1 核心端点

```
GET    /api/videos                 列表（分页、搜索、筛选、排序）
GET    /api/videos/{id}            详情（含 metadata）
DELETE /api/videos/{id}            删除记录（不删文件）
POST   /api/videos/{id}/scrape     触发刮削 {force, overwrite_manual}
PATCH  /api/videos/{id}/metadata   手动编辑 {fields, version}
PATCH  /api/videos/{id}/features   修正特征 {features, version}
POST   /api/videos/{id}/play       播放 {player?, seek?}
GET    /api/videos/{id}/cover      封面（本地缓存或代理下载）
GET    /api/videos/{id}/screenshot 截图

POST   /api/scans                  触发扫描 {root_id?, full?} → {job_id}
GET    /api/scans/{job_id}         兼容别名，等价于 /api/jobs/{id}

GET    /api/jobs/{id}              任务状态与进度
POST   /api/jobs/{id}/cancel       取消任务
GET    /api/events                 SSE 事件流（任务进度、刮削状态）

GET    /api/settings               读取设置
PUT    /api/settings               更新设置（校验后生效）
GET    /api/scan-roots             扫描根目录列表
POST   /api/scan-roots             新增
PUT    /api/scan-roots/{id}        修改
DELETE /api/scan-roots/{id}        删除（不删文件）

GET    /api/sources                源列表
POST   /api/sources                新增用户源
PUT    /api/sources/{id}           编辑源
DELETE /api/sources/{id}           删除用户源
PATCH  /api/sources/{id}           启用/优先级调整
POST   /api/sources/test           测试源配置

GET    /api/players                探测本机可用的播放器列表
```

### 8.2 异步与进度

- 扫描、批量刮削、单文件刮削统一走 `jobs`，返回 `job_id`。
- 进度通过 `GET /api/jobs/{id}` 或 SSE `/api/events` 推送；SSE 不可用时前端回退到 2 秒轮询。
- 任务可取消；取消为协作式，扫描在目录边界检查。

### 8.3 播放接口

```
POST /api/videos/{id}/play
  body: {player?: "mpv" | "vlc" | ..., seek?: 120}
  → {ok: true, player: "mpv", pid: 12345}

错误（409/422）：
  {"error": {"code": "no_player", "message": "未找到可用的播放器，请在设置中指定"}}
  可能原因码：no_player / player_not_found / path_not_found / path_outside_root
```

- 后端从 `videos.path` 取路径，校验其位于启用的扫描根目录内，然后 `exec` 播放器。
- 播放器按以下顺序解析：请求指定 → 设置默认 → 平台探测（`mpv`、`vlc`、`PotPlayerMini64.exe` 等）。
- 不等待播放器退出；启动成功后立即返回 pid，播放器进程与后端解耦、独立运行。
- `args` 模板支持 `{path}` 与 `{seek}` 占位符，由后端替换后作为独立参数数组传入。

### 8.4 播放器探测

`GET /api/players` 返回本机可用的播放器：

```json
{"players": [{"name": "mpv", "path": "C:\\Tools\\mpv\\mpv.exe", "source": "path"},
             {"name": "vlc", "path": "C:\\Program Files\\VideoLAN\\VLC\\vlc.exe", "source": "common_dir"}]}
```

- 探测范围：`PATH` 环境变量 + 各平台常见安装目录。
- 设置页可直接选择探测结果，或手动填写可执行文件路径。

### 8.5 图片接口

- 刮削成功时由后端下载封面到 `data/covers/`，下载时带上源配置的 Referer/UA；前端只访问 `/api/videos/{id}/cover`，规避防盗链与跨域。
- 无封面时返回占位图；截图接口按需查询本地文件，不存在时返回 404。
- 图片响应支持 `ETag` 与长缓存。

### 8.6 安全边界

- 默认且推荐只监听 `127.0.0.1`；本工具不面向局域网/公网暴露，第一版不提供鉴权。
- 写操作使用 JSON `Content-Type` 并校验 `Origin`/`Host`，降低恶意网页跨站调用本地接口的可能。
- 播放只接受"由 `video_id` 解析出的、位于扫描根目录内"的路径，不接受前端传入的文件路径。
- 用户自定义源可访问任意 URL，存在 SSRF 面；由于仅本机运行，风险由用户自行承担，文档提示不要填写不可信地址。

### 8.7 错误格式

```json
{"error": {"code": "version_conflict", "message": "元数据已被修改，请刷新后重试", "details": {}}}
```

- `409`：乐观锁冲突、播放器不可用；`422`：参数/源配置校验失败；`404`：资源不存在。
- 列表接口统一分页参数 `page`、`page_size`（默认 50，上限 200）与 `total`。

---

## 9. 前端页面

### 9.1 页面结构

- **海报墙**：卡片显示封面、标题、番号标签（有则显示）、年份、刮削状态角标。支持排序、筛选（按源、按是否有番号、按刮削状态、按是否缺失）与搜索。大库使用虚拟滚动与图片懒加载。
- **详情侧边栏/页**：封面、元数据字段、来源信息（哪个源、匹配特征）、刮削状态与时间、播放按钮、重新刮削按钮。每个字段旁提供"恢复自动"操作，用于移除该字段的 `manual_fields` 标记。
- **源管理页**：源列表（拖拽排序、启用开关）、新建/编辑源的 YAML 编辑器、测试按钮（第二版 Web 化，MVP 用 CLI）。
- **设置页**：扫描根目录管理、播放器选择与可执行文件路径/参数、并发数、缓存时长、文件名清洗规则、ffmpeg 路径。
- **任务中心**：扫描与批量刮削的进度、失败项与取消操作，入口为顶栏小图标 + 全局进度条。

### 9.2 不设模式切换

前端不提供"JAV 模式/视频模式"切换。所有影片在同一视图中呈现，信息密度由元数据丰富程度自然决定。番号仅作为卡片上的一个标签、详情页的一个字段存在。

### 9.3 播放交互

- 播放按钮直接调用 `/api/videos/{id}/play`，不在前端探测本地端口。
- 后端返回 `no_player` 时，引导到设置页选择探测到的播放器或手动指定路径；其余原因码直接展示。
- 前端不接触文件系统路径。

---

## 10. 技术选型与工程约束

| 层 | 推荐 | 理由 |
|----|------|------|
| 后端语言 | Python 3.12+ / FastAPI | 开发效率高、生态完整；本机单用户场景下性能足够 |
| 数据库 | SQLite（标准库 `sqlite3`） | 零部署、单文件；不引入 ORM，SQL 与迁移完全可控 |
| 前端 | React + Vite + Tailwind | 生态成熟，虚拟滚动/海报墙组件多 |
| 源配置解析 | YAML + 自定义提取器 | 用户可读；`css`/`xpath`/`json`/`regex` 四种前缀 |
| 媒体探测 | 外部 ffprobe/ffmpeg（可选） | 避免把大依赖打进二进制；缺失时优雅降级 |

工程约束：

- 依赖用 `uv` 管理（`pyproject.toml` + `uv.lock`），保证可复现；前端构建产物放在 `web/dist`，由 FastAPI `StaticFiles` 托管。
- SQLite 访问统一封装，启用 WAL、外键、busy timeout；每次操作使用短连接，写操作串行。
- 迁移、日志（标准库 `logging`，按大小轮转）、数据库备份（提供手动导出接口）从第一版具备。
- 不引入托盘/常驻子进程；`python -m vbob` 启动后即提供 Web 服务，关闭进程即退出。
- 分发优先 `uv sync` + `uv run vbob`；如需免 Python 环境，可用 PyInstaller 打包，作为后续的可选目标。
- 播放器进程与后端解耦：后端只负责启动，播放器退出或后端关闭都不影响对方。
- 测试：提取器用文件名/路径表驱动用例；源引擎用保存的 HTML/JSON 固定样本做 golden test；API 用 `pytest` + `fastapi.testclient`。

---

## 11. 开发路线

### 第一版（MVP）

按优先级排列，前 7 项为核心：

1. 设置与扫描根目录管理；扫描入库、增量扫描、缺失标记、异步任务与进度（SSE）。
2. 特征提取（番号/标题/年份、清洗规则、目录名回退）。
3. 源配置加载与执行引擎：`css`/`xpath`/`json`/`regex`、编码探测、超时/重试/按 host 限流、匹配校验；CLI 源测试命令。
4. 刮削调度器：两轮降级、番号回验、字段级手动覆盖、并发、缓存、日志。
5. 海报墙 + 详情页 + 元数据/特征编辑（含"恢复自动"）+ 重新刮削。
6. 封面代理与本地缓存、截图生成（ffmpeg 可选）。
7. 播放：后端直接调起本地播放器，支持播放器配置、自动探测与参数模板。
8. 内置两个源：一个番号源（JavBus 或 JavDB）、一个通用源（TMDB，key 在设置页填写）。

### 第二版

- 源配置 Web 编辑界面 + 测试功能（含选择器语法即时校验）。
- 基于播放器 IPC（优先 mpv JSON IPC）的播放进度与"继续观看"。
- 播放器参数预设与多播放器管理。
- 季集提取器。
- 缺失文件批量清理界面、按 `size+mtime` 的重复项提示。
- 源健康度、失败冷却/熔断、内置源升级提示。
- 封面缓存清理策略、数据库自动备份。

### 第三版

- 磁力链接获取与下载队列（可选，依赖 aria2/CloudDrive2）。
- 女优/厂商/系列聚合浏览。
- 批量刮削任务队列的增强界面（重试失败项、按源统计）。

---

## 12. 风险与注意事项

- **源站反爬**：内置源可能因目标站点改版或封禁失效。通过 `builtin` 可禁用、用户源可替代、cookies/proxy/限流配置来缓解；文档中明确"内置源不保证长期可用"。
- **法律与合规**：项目定位为"本地文件元数据管理工具"，不提供内容下载、不内置盗版资源链接。内置番号源仅抓取公开元数据页面，需在 README 中声明用途与免责，并遵守目标站点 robots/ToS。
- **播放器差异**：不同播放器的参数语法不同（如 mpv 的 `--start`、VLC 的 `--start-time`），MVP 只保证启动；seek 与进度相关能力按播放器适配。
- **手动编辑与自动刮削冲突**：以字段级 `manual_fields` + `version` 乐观锁保证，所有写路径（单文件、批量、特征修改）必须走同一合并函数。
- **安全边界**：默认仅监听本地、无鉴权，不要改为对外地址；用户自定义源存在 SSRF 面，仅在本机使用。
- **分发与依赖**：Python 运行环境的获取是主要门槛，优先用 `uv` 一键运行/安装，后续用 PyInstaller 降低门槛；ffmpeg 为可选依赖，缺失时降级。
- **Windows 细节**：大小写不敏感路径、长路径、SmartScreen 可能影响首次运行；安装包与文档需覆盖。
- **源结果错误匹配**：番号回验与标题相似度校验是数据质量的生命线，任何新增源都必须通过校验测试。

---

## 13. 相对初稿的主要变更

1. **播放链路**：前端只调后端，由后端直接 `exec` 本地播放器；不引入播放助手、WSS、配对与路径映射（v0.3 起明确仅支持单机本地运行）。
2. **新增配置与任务模型**：新增 `settings`、`scan_roots`、`jobs` 表；扫描/批量刮削全部异步化，支持进度与取消。
3. **库同步语义**：`videos` 增加 `path_key`、`present`、`missing_since`；明确增量扫描、缺失标记与清理流程；补充扫描规则章节。
4. **图片链路前移**：封面代理与本地缓存、截图接口进入 MVP；新增 `/api/videos/{id}/cover|screenshot`。
5. **数据模型修正**：`metadata.video_id` 加 `UNIQUE`；新增 `created_at`、`scrape_status`、`last_scraped_at`、`version`；用 `manual_fields` 取代 `manual_edited`；`jav_code` 生成列 + 索引。
6. **源配置增强**：明确选择器方言（CSS 不支持 `:contains`，改用 XPath）；新增 charset、timeout、retry、按 host 限流、cookies/proxy；统一占位符命名；补充匹配校验（番号回验、标题相似度、错误页检测）。
7. **番号归一化修正**：按族定义格式与比较键，取消全局补零；增加词边界与停用词黑名单；提取输入包含目录名。
8. **调度器补全**：明确跨类型优先级语义、字段级合并与乐观锁、负缓存、按 host 限流。
9. **路线图修订**：特征修正前移 MVP；修正初稿中两处矛盾。
10. **工程与安全**：SQLite 短连接 + 迁移/日志/备份；默认本地绑定、SSRF 提示；源测试 CLI 进入 MVP。
11. **v0.3 范围收敛**：取消 Docker/NAS 部署与播放助手组件，删除远程播放协议、配对、路径映射及相关风险条目；架构简化为单机单进程，播放由后端直接调起本地播放器。
12. **v0.4 技术栈调整**：后端由 Go 改为 Python 3.12+ / FastAPI，SQLite 使用标准库 `sqlite3`；提取器接口、选择器实现建议、工程约束与分发方式同步更新。

---

## 14. v0.5 增量需求：演员体系、完整度、收藏与设置重构

> 2026-10-29 需求评审确认。本节覆盖第 3、6、7、8、9 节中与本节冲突的描述；实现以本节为准。

### 14.1 完整度与"缺失"语义

**视频必填字段**（用于完整度判断，不作为刮削失败条件）：

1. 影视名称 `title`
2. 发行日期 `release_date`
3. 演员表：至少关联 1 位演员
4. 标签：至少 1 个
5. 封面：本地封面文件存在（`cover_local`）
6. 时长：`metadata.runtime_sec` 或 `videos.duration_sec` 大于 0

可选字段：番号 `code`、系列 `series`、是否有码 `censored`、国家/地区 `country`、厂商、导演、简介。

**演员必填字段**：

1. 姓名 `name`
2. 出生日期 `birth_date`
3. 国籍 `nationality`
4. 封面：本地封面文件存在（`cover_local`）

可选：身高、三围、罩杯、别名。

规则：

- `metadata.is_complete` / `actresses.is_complete` 在刮削、手动编辑、封面更新、演员关联变化后重新计算。
- `scrape_status` 只表示"是否有源匹配/抓取过程是否成功"，与完整度分开：抓取成功但缺字段 → `success` + 不完整；没有源匹配 → `no_match`；网络/解析错误 → `failed`。
- **缺字段绝不导致刮削失败**；只影响完整度、筛选和统计。
- 目录管理中的"已刮削"= 该目录下 `metadata.is_complete=1` 的视频数。
- **不专门管理缺失文件**：扫描未发现的记录仅标记 `present=0`，默认不出现在列表中；不提供缺失筛选、清理入口或相关菜单。刮削失败/不完整仍可单独筛选。
- 视频完整度不要求其关联演员的资料完整；演员完整度独立计算。

### 14.2 数据模型增量

```sql
-- 视频收藏
ALTER TABLE videos ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0;

-- 视频元数据扩展
ALTER TABLE metadata ADD COLUMN censored TEXT;       -- censored | uncensored | unknown
ALTER TABLE metadata ADD COLUMN country TEXT;        -- 自由文本
ALTER TABLE metadata ADD COLUMN is_complete INTEGER NOT NULL DEFAULT 0;
-- metadata.actresses 保留为兼容字段，不再作为演员数据源

-- 演员
CREATE TABLE actresses (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    name_key      TEXT NOT NULL UNIQUE,          -- NFKC + casefold + 空白归一
    aliases       TEXT NOT NULL DEFAULT '[]',    -- JSON array
    birth_date    TEXT,
    nationality   TEXT,
    cover_url     TEXT,
    cover_local   TEXT,
    profile_url   TEXT,                          -- 来源演员页
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

-- 视频-演员关联
CREATE TABLE video_actresses (
    video_id   INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    actress_id INTEGER NOT NULL REFERENCES actresses(id) ON DELETE CASCADE,
    position   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (video_id, actress_id)
);

-- 扫描目录：自动扫描与统计
ALTER TABLE scan_roots ADD COLUMN scan_interval_minutes INTEGER NOT NULL DEFAULT 0; -- 0=关闭
ALTER TABLE scan_roots ADD COLUMN last_scan_started_at TEXT;
ALTER TABLE scan_roots ADD COLUMN last_scan_finished_at TEXT;
ALTER TABLE scan_roots ADD COLUMN last_scan_status TEXT;       -- idle/running/succeeded/failed/canceled
ALTER TABLE scan_roots ADD COLUMN last_scan_duration_ms INTEGER;

-- 任务归属目录，便于按目录展示扫描/刮削进度
ALTER TABLE jobs ADD COLUMN root_id INTEGER REFERENCES scan_roots(id) ON DELETE SET NULL;
```

索引：

```sql
CREATE INDEX idx_actresses_name_key     ON actresses(name_key);
CREATE INDEX idx_actresses_favorite     ON actresses(favorite);
CREATE INDEX idx_actresses_complete     ON actresses(is_complete);
CREATE INDEX idx_video_actresses_actress ON video_actresses(actress_id);
CREATE INDEX idx_metadata_complete      ON metadata(is_complete);
CREATE INDEX idx_videos_favorite        ON videos(favorite);
CREATE INDEX idx_jobs_root              ON jobs(root_id);
```

补充规则：

- 演员按 `name_key` 去重；不同写法的别名存入 `aliases`。具体合并/别名管理 UI 留到后续版本，但字段先保留。
- 删除演员：存在关联视频时返回 `409`，必须先解除关联；删除视频会级联删除关联，演员保留，之后可删除。
- 收藏为单用户布尔字段，视频与演员各一个。
- 封面文件路径：`data/covers/videos/{id}.jpg`、`data/covers/actresses/{id}.jpg`，数据库只存相对路径。

### 14.3 演员刮削源与多源合并

源类型扩展为 `feature | query | actress`。

**视频源**额外支持结构化演员提取：

```yaml
extract:
  actresses:
    selector: "css: .star-name a"
    name: "@text"
    url: "@href"        # 可选，演员详情页地址
```

**演员源**（`type: actress`）：

- 占位符：`{actress_name}`、`{actress_url}`。
- 提取字段：`name`、`birth_date`、`nationality`、`cover_url`、`height_cm`、`bust_cm`、`waist_cm`、`hips_cm`、`cup`、`aliases`。
- 演员源只负责补全演员资料，不影响视频刮削结果。

调度规则：

- 视频刮削从"第一个有效源直接返回"改为**按优先级逐源合并**：手动字段优先，其余字段按源优先级取第一个非空值，直到必填字段齐全或源耗尽；保存部分结果并计算完整度。
- 演员在视频刮削时按 `name_key` 自动创建（至少写入姓名）；若视频源提供演员详情页 URL，则记录 `profile_url`。
- 视频刮削完成后，对资料不完整的演员按优先级运行演员源；失败不影响视频完整度。
- 批量刮削按目录触发：默认只处理不完整视频，支持"强制重刮"和"覆盖手动编辑"。
- 源测试接口需同时支持视频源与演员源。

### 14.4 扫描与目录管理

- `scan_roots.scan_interval_minutes`：自动扫描间隔，0 表示关闭（默认）。后台调度器每 60 秒检查一次；若该目录没有进行中的任务且距上次扫描超过间隔，则创建扫描任务。
- **编辑目录地址**：`PATCH /api/scan-roots/{id}` 可修改 `path`。修改时在同一事务内：
  1. 校验新目录存在且不与其它目录重叠；
  2. 对该目录下已有视频按"旧根目录 → 相对路径 → 新根目录"重写 `path`/`path_key`；
  3. 路径冲突时拒绝修改；
  4. 元数据、收藏、视频 ID 全部保留；文件实际不在新位置时，下次扫描标记为缺失。
  这样可解决"文件夹改名后扫描不到、元数据重新入库"的问题。
- 目录行操作（对应参考图）：
  - 手动扫描
  - 批量刮削
  - 扫描设置（自动扫描间隔）
  - 编辑（修改目录地址）
  - 删除
  - 取消"工具"按钮
- 目录行展示：
  - 已扫描数量 = 该目录视频总数
  - 已刮削数量 = `is_complete=1` 的视频数
  - 当前状态 = 空闲 / 扫描中 / 刮削中（按该目录的活动任务）
  - 上次扫描开始/结束时间与耗时
- 扫描与批量刮削任务按目录拆分（`jobs.root_id`），"扫描全部"为每个启用目录创建任务，进度直接显示在目录行。

### 14.5 手动编辑与封面

- `PATCH /api/videos/{id}/metadata`：可修改全部视频字段，包括标题、发行日期、标签数组、演员列表（ID 或姓名，姓名不存在时自动创建）、番号、系列、有码状态、国家/地区、时长、简介等。
- `PATCH /api/actresses/{id}`：可修改演员全部字段。
- 字段级 `manual_fields`：手动字段不被自动刮削覆盖；强制重刮时可选择覆盖。
- 封面：
  - 支持上传本地文件（multipart）或提供图片 URL（后端下载）；
  - 后端校验格式（jpeg/png/webp）与大小（默认 ≤10MB），保存到本地并写入 `cover_local`；
  - 视频与演员分别提供上传/URL 设置接口；
  - 刮削得到的封面 URL 也由后端自动下载缓存；下载失败时保留 `cover_url`，但不算"本地封面"，完整度不满足。
- 所有写操作继续使用 `metadata.version` / `actresses.version` 乐观锁。

### 14.6 API 增量

```text
GET    /api/videos?complete=&favorite=&actress_id=&tag=&censored=&sort=
PATCH  /api/videos/{id}/metadata       手动编辑全部字段 {fields, version}
PATCH  /api/videos/{id}/favorite       {favorite}
POST   /api/videos/{id}/cover          上传本地封面（multipart）
PUT    /api/videos/{id}/cover          {url} 下载图床/源站封面

GET    /api/actresses                  列表（搜索、完整度、收藏、视频数排序）
POST   /api/actresses                  新建演员 {name}
GET    /api/actresses/{id}             详情 + 关联视频
PATCH  /api/actresses/{id}             编辑演员
DELETE /api/actresses/{id}             有关联视频时 409
PATCH  /api/actresses/{id}/favorite    {favorite}
POST   /api/actresses/{id}/cover       上传封面
PUT    /api/actresses/{id}/cover       {url} 下载封面

PATCH  /api/scan-roots/{id}            {path?, scan_interval_minutes?, enabled?}
POST   /api/scrapes                    {root_id?, video_ids?, force?, overwrite_manual?}
POST   /api/scans                      {root_id?, full?}（按目录创建任务）
GET    /api/sources?type=             视频源/演员源
POST   /api/sources/test               视频源与演员源测试
```

### 14.7 前端结构

- 左侧菜单：
  - 视频（海报墙；卡片展示必填项，有番号时额外显示番号）
  - 演员（海报墙；卡片展示姓名、出生日期、国籍、封面、收录视频数量）
  - 收藏（可展开：收藏的视频、收藏的演员）
  - 底部：深/浅主题、设置
- 不提供"文件缺失"菜单或筛选；视频页保留"刮削不完整/失败"筛选。
- 视频与演员均支持"编辑全部信息"表单；演员多选支持就地新建；标签为多值编辑器。
- 设置改为**不可拖动的弹窗**，左侧设置项、右侧内容：
  - 目录管理：目录行 + 统计 + 手动扫描/批量刮削/扫描设置/编辑/删除 + 添加目录
  - 播放器：探测结果、自定义路径与参数
  - 刮削源：源列表 + 图形化表单（视频源/演员源），常用字段图形化，保留"高级 YAML"兜底；支持多源、启用/禁用、优先级、测试
- 批量刮削与扫描进度直接显示在对应目录行。

### 14.8 实施顺序

1. **数据与编辑基础**：迁移（演员表/关联表/收藏/新字段/扫描统计）、完整度计算、手动编辑 API、封面上传与缓存。
2. **视频页面**：菜单与路由、视频卡片字段、全部信息编辑、收藏、文件缺失/不完整筛选。
3. **演员体系**：演员海报墙、详情、视频数量、收藏、删除约束。
4. **刮削引擎**：视频多源合并、演员源、演员详情抓取、批量刮削与进度。
5. **设置重构**：弹窗、目录管理统计/路径编辑/自动扫描、图形化源配置与测试。

### 14.9 默认约定

- 自动扫描默认关闭（`0`）；建议最小间隔 5 分钟。
- 批量刮削默认只处理不完整视频；"扫描后自动刮削"暂不默认开启。
- 图片格式 jpeg/png/webp，默认上限 10MB。
- 国家/地区为自由文本；有码状态为 `censored/uncensored/unknown`。
- 演员别名合并 UI 后续实现，当前先保留 `aliases` 字段并自动创建演员。
