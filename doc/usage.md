# VBob 使用文档

> 适用版本：0.1.0（2026-10-29）
>
> 设计说明见 [design.md](design.md)，接口文档启动后访问 <http://127.0.0.1:8080/docs>。

## 1. 简介

VBob 是一个单机运行的本地视频管理器：扫描本地目录中的视频文件、提取番号/标题/年份等特征、在 Web 页面中浏览和筛选，并调用本机播放器播放。

当前版本已经打通"扫描 → 浏览 → 播放"链路。刮削源的配置与校验已经可用，抓取执行与元数据写回将在下一阶段接入。

## 2. 环境要求

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | 3.12+ | 后端运行时 |
| uv | 最新版 | 依赖与虚拟环境管理 |
| Node.js / npm | 20+ | 仅在构建前端时需要 |
| mpv / VLC / PotPlayer | 任选其一 | 播放视频；也可以稍后在配置中指定路径 |
| ffmpeg / ffprobe | 可选 | 后续用于时长与截图，当前版本不强制 |

## 3. 安装与启动

```bash
# 1. 安装后端依赖
uv sync --extra dev

# 2. 构建前端（首次运行或前端代码变更后）
cd web
npm install
npm run build
cd ..

# 3. 启动
uv run vbob --open
```

默认访问地址：<http://127.0.0.1:8080>

常用参数：

```bash
uv run vbob --port 8081          # 换端口
uv run vbob --data-dir D:\VBob   # 指定数据目录
uv run vbob --host 127.0.0.1     # 监听地址（不建议改为对外地址）
```

前端开发模式：

```bash
cd web && npm run dev   # http://127.0.0.1:5173，/api 自动代理到 8080
uv run vbob             # 另一个终端
```

## 4. 首次使用

1. 打开设置页（左侧栏底部「设置」）。
2. 在「扫描目录」中添加视频所在目录，例如 `D:\Media`。
3. 点击「扫描全部」或某个目录右侧的「扫描」。
4. 扫描完成后回到「视频库」查看结果。

扫描规则：

- 默认扩展名：`mp4 mkv avi wmv mov ts m2ts mpg mpeg flv webm rmvb m4v`。
- 默认忽略小于 50MB 的文件（可在 API 设置中调整 `scan.min_size_mb`）。
- 跳过隐藏文件/目录、系统目录（如 `$RECYCLE.BIN`、`System Volume Information`、`@eaDir`）。
- 默认不跟随符号链接；嵌套的扫描目录会被拒绝。
- 增量扫描：文件大小与修改时间都没变时跳过；文件消失时标记为「缺失」，不自动删除记录。

## 5. 界面说明

### 5.1 视频库

- 左侧导航：视频库、缺失文件、全部视频。
- 顶部：搜索、排序（加入时间 / 文件名 / 年份 / 番号）、扫描。
- 卡片展示番号、标题、时长、年份、厂商以及类型/标签/演员信息。
- 卡片底部操作：播放、查看详情、删除记录。

### 5.2 筛选与搜索

- 「视频库」只显示当前存在的文件；「缺失文件」显示扫描后发现已删除或移动的文件；「全部视频」不过滤。
- 搜索匹配文件名、路径、标题与番号。

### 5.3 详情与播放

点击卡片或信息按钮打开详情抽屉，可查看完整元数据、文件路径、提取的特征。

点击播放后，后端会：

1. 按 `video_id` 取出文件路径并确认位于扫描目录内；
2. 按「请求指定播放器 → 设置中的播放器 → 自动探测」的顺序选择播放器；
3. 启动播放器进程并立即返回，不阻塞页面。

自动探测顺序与常见路径：

- mpv：`PATH`、`C:\Program Files\mpv\mpv.exe`、`%LOCALAPPDATA%\Programs\mpv\mpv.exe`
- VLC：`PATH`、`C:\Program Files\VideoLAN\VLC\vlc.exe`
- PotPlayer：`C:\Program Files\DAUM\PotPlayer\PotPlayerMini64.exe`
- Linux/macOS：`mpv`、`vlc`、`celluloid` 或常见应用目录

### 5.4 主题

左下角可在浅色/深色主题之间切换，选择保存在浏览器 `localStorage`。

也可以在地址后加参数直接指定（便于分享或排障）：

```
http://127.0.0.1:8080/?theme=light
http://127.0.0.1:8080/?theme=dark
```

## 6. 设置页

### 6.1 扫描目录

- 添加、移除目录，单独扫描某个目录或扫描全部。
- 移除目录不会删除视频文件；该目录下的记录会被标记为缺失。

### 6.2 刮削源

- 「新增源」打开 YAML 编辑器，保存时后端会做结构化校验。
- 每个源可以单独启用/禁用；用户源的优先级可在 YAML 的 `priority` 中调整。
- 内置源（`builtin: true`）只能启用/禁用和调整优先级，不能编辑或删除。
- 当前版本保存的源配置会被持久化并校验；实际的抓取执行与元数据写回尚未接入。

### 6.3 播放器

展示后端探测到的播放器。未检测到时，安装 mpv / VLC / PotPlayer 后点击「重新检测」，或通过 API 指定播放器路径（见 8.2）。

### 6.4 外观

浅色与深色主题切换，与左下角按钮等价。

## 7. 刮削源配置参考

源配置使用 YAML（存储时转换为 JSON），顶层字段：

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | 是 | 唯一名称，最长 64 字符 |
| `type` | 是 | `feature`（按特征查询）或 `query`（按标题搜索，作为降级） |
| `feature` | feature 类型必填 | 使用哪个特征，如 `jav_code` |
| `enabled` | 否 | 默认 `true` |
| `priority` | 否 | 越小越先尝试，默认 100 |
| `request` | 是 | 至少包含 `url`；可选 `method`、`headers` 等 |
| `extract` | 是 | 字段名到提取表达式的映射 |
| `validators` | 否 | 校验规则数组 |

提取表达式必须以以下前缀之一开头：

| 前缀 | 说明 |
|------|------|
| `css:` | CSS 选择器；可选 `@属性`，缺省取文本。不支持 jQuery 的 `:contains()`，按文本匹配请用 XPath |
| `xpath:` | XPath 1.0 表达式 |
| `json:` | JMESPath 表达式，例如 `results[0].title` |
| `regex:` | 正则表达式，取第 1 个捕获组 |

示例（番号源）：

```yaml
name: javbus
enabled: true
priority: 10
type: feature
feature: jav_code

request:
  url: "https://www.javbus.com/{jav_code}"
  method: GET
  headers:
    User-Agent: "Mozilla/5.0 ..."

extract:
  title: "xpath: //h3/text()"
  cover_url: "css: .bigImage img@src"
  release_date: "xpath: //span[contains(text(),'發行日期')]/following-sibling::span/text()"

validators:
  - field: title
    required: true
```

示例（搜索源）：

```yaml
name: example-search
enabled: true
priority: 100
type: query

request:
  url: "https://example.com/search?q={title}&year={year}"
  method: GET

extract:
  title: "css: .result h2@text"
  cover_url: "css: .result img@src"

validators:
  - field: title
    required: true
```

占位符使用特征键名：`{jav_code}`、`{title}`、`{year}`；值会自动进行 URL 编码。

## 8. 通过 API 调整配置

启动后访问 <http://127.0.0.1:8080/docs> 可查看完整的 OpenAPI 文档。以下为常用示例（Windows 路径建议使用正斜杠或正确转义）。

### 8.1 修改扫描设置

```bash
curl -X PUT http://127.0.0.1:8080/api/settings \
  -H "Content-Type: application/json" \
  -d '{"scan":{"min_size_mb":0,"extensions":["mp4","mkv"],"ignore_globs":["*sample*"]}}'
```

可配置项：

```json
{
  "scan": {
    "extensions": ["mp4", "mkv"],
    "ignore_globs": ["*sample*", "*trailer*"],
    "min_size_mb": 50,
    "follow_symlinks": false
  },
  "scraping": {
    "clean_rules": [],
    "workers": 3,
    "cache_ttl_sec": 600,
    "negative_ttl_sec": 60
  },
  "playback": {
    "player": null
  }
}
```

### 8.2 指定播放器

```bash
curl -X PUT http://127.0.0.1:8080/api/settings \
  -H "Content-Type: application/json" \
  -d '{"playback":{"player":{"name":"mpv","path":"C:/Tools/mpv/mpv.exe","args":["--fullscreen","{path}"]}}}'
```

- 参数模板支持 `{path}` 与 `{seek}`；如果模板中没有 `{path}`，后端会自动把文件路径追加到末尾。
- 播放接口：`POST /api/videos/{id}/play`，可传 `{"player":"mpv","seek":120}`。

### 8.3 扫描与管理

```bash
# 添加目录
curl -X POST http://127.0.0.1:8080/api/scan-roots \
  -H "Content-Type: application/json" \
  -d '{"path":"D:/Media"}'

# 触发扫描，返回 job_id
curl -X POST http://127.0.0.1:8080/api/scans \
  -H "Content-Type: application/json" -d '{}'

# 查询任务进度
curl http://127.0.0.1:8080/api/jobs/<job_id>

# 取消任务
curl -X POST http://127.0.0.1:8080/api/jobs/<job_id>/cancel
```

## 9. 数据目录与备份

默认数据目录：

- Windows：`%LOCALAPPDATA%\VBob`
- macOS：`~/Library/Application Support/VBob`
- Linux：`$XDG_DATA_HOME/vbob`（默认 `~/.local/share/vbob`）

可用 `--data-dir` 或环境变量 `VBOB_DATA_DIR` 覆盖。

```
<data-dir>/
  vbob.db          # SQLite 数据库（WAL 模式）
  covers/          # 封面缓存（后续版本使用）
  screenshots/     # 截图（后续版本使用）
  logs/vbob.log    # 运行日志（按大小轮转）
```

备份：停止服务后复制整个数据目录即可。数据库使用 WAL 模式，建议同时复制 `vbob.db-wal`、`vbob.db-shm`，或先停止服务再复制。

## 10. 常见问题

**扫描后没有视频**

- 文件可能小于默认的 50MB；通过 `PUT /api/settings` 调整 `scan.min_size_mb`。
- 检查扩展名是否在白名单中；隐藏文件、系统目录、被 `ignore_globs` 匹配的文件会被跳过。
- 文件必须位于已添加的扫描目录内，且扫描目录不能互相嵌套。

**文件被标为缺失**

文件已删除、改名或移动。记录不会被自动清理；文件恢复后再次扫描会自动恢复为在库状态。

**播放提示 `no_player`**

没有检测到播放器。安装 mpv/VLC/PotPlayer，或在设置中通过 API 指定 `playback.player.path` 后重试。

**播放提示 `path_outside_root` / `path_not_found`**

文件不在扫描目录内，或已被移动/删除。重新扫描或检查目录配置。

**端口被占用**

使用 `uv run vbob --port 8081` 换端口。

**保存刮削源报错**

- YAML 语法错误会显示解析位置；
- `type` 必须是 `feature` 或 `query`；
- `feature` 类型必须提供 `feature` 字段；
- 提取表达式必须以 `css:` / `xpath:` / `json:` / `regex:` 开头；
- 源名称不能重复。

**如何重置**

停止服务，备份后删除数据目录中的 `vbob.db` 及 WAL 文件，重启会重新建库。此操作会清空扫描记录、设置与源配置。

## 11. 当前限制与后续计划

当前版本尚未实现：

- 刮削调度与源抓取执行（源配置已可管理，但不会自动抓取元数据）；
- 封面下载/缓存与截图；
- 元数据手动编辑与手动修正特征；
- SSE 实时进度推送（当前为轮询）；
- 源配置测试与 Web 端播放器路径设置。

后续将按设计文档第 11 节的路线继续实现。

## 12. 安全说明

- 默认只监听 `127.0.0.1`，不提供鉴权，请勿将服务暴露到局域网或公网。
- 用户自定义的刮削源 URL 由本机后端直接请求，存在访问任意地址的可能；只填写可信来源。
- 播放只接受由 `video_id` 解析出、且位于扫描目录内的文件路径。
