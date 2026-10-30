# VBob 使用文档

> 适用版本：0.1.0（2026-10-29）
>
> 设计说明见 [design.md](design.md)，接口文档启动后访问 <http://127.0.0.1:8080/docs>。

## 1. 简介

VBob 是一个单机运行的本地视频管理器：扫描本地目录中的视频、提取番号/标题/年份、在 Web 页面中浏览和管理视频与演员，并调用本机播放器播放。

当前版本已具备：

- 视频 / 演员 / 收藏三个栏目的海报墙；
- 视频与演员资料的全字段手动编辑；
- 视频、演员封面本地上传或 URL 下载；
- 完整度统计、收藏、深色/浅色主题；
- 目录自动扫描间隔、目录路径重映射；
- 图形化刮削源配置（视频源、演员源）。

当前已接入刮削引擎：支持单视频重刮、按目录批量刮削、视频源/演员源、封面下载、逐源日志与完整度更新。

## 2. 环境要求

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | 3.12+ | 后端运行时 |
| uv | 最新版 | 依赖与虚拟环境管理 |
| Node.js / npm | 20+ | 仅在构建前端时需要 |
| mpv / VLC / PotPlayer | 任选其一 | 播放视频；也可以在设置中指定路径 |
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

1. 点击左下角「设置」，打开全局设置弹窗。
2. 在「目录管理」中添加视频目录，例如 `D:\Media`。
3. 点击「扫描全部」或某个目录右侧的「手动扫描」。
4. 扫描完成后回到「视频」查看海报墙；点击卡片进入详情，可编辑全部信息、上传封面、收藏或播放。

扫描规则：

- 默认扩展名：`mp4 mkv avi wmv mov ts m2ts mpg mpeg flv webm rmvb m4v`。
- 默认忽略小于 50MB 的文件（可通过 API 调整 `scan.min_size_mb`）。
- 跳过隐藏文件/目录、系统目录（如 `$RECYCLE.BIN`、`System Volume Information`、`@eaDir`）。
- 默认不跟随符号链接；嵌套的扫描目录会被拒绝。
- 增量扫描：文件大小与修改时间都没变时跳过。
- 扫描时消失的文件只会在内部标记为不存在，**不提供缺失文件菜单或清理界面**，默认也不会出现在列表里。

## 5. 界面说明

### 5.1 菜单

左侧菜单：

- **视频**：视频海报墙。
- **演员**：演员海报墙，显示姓名、出生日期、国籍、封面和收录作品数。
- **收藏**：可展开「收藏的视频」「收藏的演员」。
- 底部：深色/浅色主题切换、设置。

### 5.2 视频海报墙

卡片展示视频必填信息：

- 名称、发行日期、时长、演员、标签、封面；
- 有番号时额外显示番号；
- 有码/无码、完整度（待补全）标记、收藏心形按钮；
- 底部操作：播放、详情、收藏、删除记录。

顶部支持搜索（标题/文件名/番号/演员）、排序（加入时间/文件名/年份/番号）和扫描。

### 5.3 演员海报墙

卡片展示演员姓名、出生日期、国籍、封面、作品数、完整度与收藏按钮。顶部可按作品数、姓名、出生日期排序。

### 5.4 详情与编辑

- 视频详情抽屉可查看全部字段、本地路径、提取特征和刮削日志，并进入「编辑视频信息」。
- 详情右上角的刮削图标可对单个视频重新刮削；任务进度显示在页面顶部。
- 演员详情抽屉可查看资料、收录作品列表，并进入「编辑演员信息」。
- 视频编辑支持：名称、原名、番号、发行日期、时长（分钟）、有码状态、国家/地区、系列、厂商、导演、演员（逗号分隔，可新建）、类型、标签、简介、封面。
- 演员编辑支持：姓名、别名、出生日期、国籍、身高、三围、罩杯、资料页 URL、封面。
- 手动修改的字段会被标记，后续自动刮削不会覆盖（除强制重刮外）。

### 5.5 完整度

- **视频完整**：名称、发行日期、至少 1 位演员、至少 1 个标签、本地封面、时长（源时长或文件时长）都存在。
- **演员完整**：姓名、出生日期、国籍、本地封面都存在。
- 视频完整度与演员资料完整度独立计算。
- 缺少信息只会显示「待补全」，不会导致刮削失败。

### 5.6 主题

左下角可在浅色/深色主题间切换，选择保存在浏览器 `localStorage`。也可以使用地址参数：

```
http://127.0.0.1:8080/?theme=light
http://127.0.0.1:8080/?theme=dark
```

## 6. 设置弹窗

设置以不可拖动的弹窗打开，左侧为设置项，右侧为内容。

### 6.1 目录管理

每个目录显示：

- 已扫描视频数；
- 已刮削数（字段完整的视频数）；
- 当前状态（空闲 / 扫描中 / 刮削中）；
- 上次扫描开始时间、耗时；
- 自动扫描间隔。

操作：

- **手动扫描**：只扫描该目录。
- **批量刮削**：对该目录下资料不完整的视频依次执行刮削，进度显示在目录行和页面顶部。
- **扫描设置**：设置自动扫描间隔（分钟，0 表示关闭；建议至少 5 分钟）。服务运行期间由后台调度器检查并自动扫描。
- **编辑路径**：目录被改名/移动后，在这里修改为新地址。已有视频会按相对路径迁移，元数据、收藏和视频 ID 都会保留。
- **删除**：移除目录配置，不删除文件。
- **添加目录**：输入路径和可选的自动扫描间隔。

"已刮削"按字段完整统计，不是"抓取动作成功"。

### 6.2 播放器

展示后端探测到的播放器（mpv / VLC / PotPlayer）。安装后点击「重新检测」即可；如需指定路径，可通过 API 配置 `playback.player`（见 9.2）。

### 6.3 刮削源

- 支持多个源，优先级数值越小越先执行。
- 源类型：
  - `feature`：按番号等特征查询；
  - `query`：按标题搜索（降级）；
  - `actress`：演员资料源。
- 图形化表单支持：名称、类型、特征、优先级、启用、请求 URL/方法/响应编码、提取字段（字段名 + css/xpath/json/regex + 表达式）。
- 提取字段在界面中显示为中文：
  - 视频源：名称、番号、发行日期、演员、标签、封面、时长、系列、是否有码、国家/地区、厂商、简介。
  - 演员源：姓名、出生日期、国籍、封面、身高、胸围、腰围、臀围、罩杯、别名、资料页 URL。
- 对应内部键名：视频源 `title`、`code`、`release_date`、`actresses`、`tags`、`cover_url`、`runtime_sec`、`series`、`censored`、`country`、`studio`、`overview`；演员源 `name`、`birth_date`、`nationality`、`cover_url`、`height_cm`、`bust_cm`、`waist_cm`、`hips_cm`、`cup`、`aliases`、`profile_url`。
- 常用选择器：`css: .title@text`、`xpath: //h3/text()`、`json: results[0].title`、`regex: ([A-Z]+-\\d+)`。
- 数组字段（演员、标签）在表达式后加 `| array`，例如 `css: .star a@text | array`。
- 占位符使用内部键名：`{jav_code}`、`{code}`、`{title}`、`{year}`、`{actress_name}`、`{actress_url}`。
- 保存时会做结构校验；内置源只能启用/禁用或调优先级，不能编辑/删除。
- 刮削执行按优先级逐源合并，手动编辑过的字段不会被覆盖；封面 URL 会自动下载到本地。
- 每次源尝试都会写入刮削日志，可在视频详情的「刮削日志」中查看成功/失败原因。

**补全演员资料**

视频页通常只显示演员姓名，生日、三围、封面需要再打开演员详情页。配置方法：

1. 在视频源底部勾选「演员使用“姓名 + 演员页链接”提取」：
   - 演员链接选择器：例如 `xpath: //div[contains(@class,"star-box")]//a[@title]`
   - 姓名表达式：`@title`
   - URL 表达式：`@href`
2. 新增一个类型为「演员资料源」的源，请求 URL 填 `{actress_url}`，提取字段选择出生日期、国籍、封面、身高、胸围、腰围、臀围、罩杯等。
3. 视频刮削时会把演员页 URL 写入演员记录；之后可在演员详情右上角点击刮削图标，或让视频刮削自动补全未完整的演员。

演员源示例（JavBus 演员页）：

```yaml
name: javBusActress
type: actress
priority: 20
request:
  url: "{actress_url}"
  rate_limit: { qps: 1 }
extract:
  birth_date: 'xpath: //div[contains(@class,"avatar-box")]//p[contains(.,"生日")]/text()'
  height_cm: 'xpath: //div[contains(@class,"avatar-box")]//p[contains(.,"身高")]/text()'
  cup: 'regex: 罩杯[:：]\s*([A-Za-z]+)'
  bust_cm: 'xpath: //div[contains(@class,"avatar-box")]//p[contains(.,"胸圍")]/text()'
  waist_cm: 'xpath: //div[contains(@class,"avatar-box")]//p[contains(.,"腰圍")]/text()'
  hips_cm: 'xpath: //div[contains(@class,"avatar-box")]//p[contains(.,"臀圍")]/text()'
  cover_url: 'xpath: //div[contains(@class,"avatar-box")]//img/@src'
defaults:
  nationality: "日本"
```

## 7. 封面

- 视频封面：`POST /api/videos/{id}/cover`（上传文件）或 `PUT /api/videos/{id}/cover`（图片 URL）。
- 演员封面：`/api/actresses/{id}/cover`，方式相同。
- 支持 jpeg/png/webp，默认上限 10MB。
- 图片保存到本地数据目录，数据库只存相对路径；URL 方式会先下载再保存。

## 8. 通过 API 调整配置

完整 OpenAPI 文档：<http://127.0.0.1:8080/docs>。

### 8.1 扫描设置

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

播放接口：`POST /api/videos/{id}/play`，可传 `{"player":"mpv","seek":120}`。

### 8.3 扫描与目录

```bash
# 添加目录（可带自动扫描间隔）
curl -X POST http://127.0.0.1:8080/api/scan-roots \
  -H "Content-Type: application/json" \
  -d '{"path":"D:/Media","scan_interval_minutes":15}'

# 修改目录地址 / 间隔
curl -X PUT http://127.0.0.1:8080/api/scan-roots/1 \
  -H "Content-Type: application/json" \
  -d '{"path":"D:/Media-renamed","scan_interval_minutes":30}'

# 触发扫描
curl -X POST http://127.0.0.1:8080/api/scans \
  -H "Content-Type: application/json" -d '{"root_id":1}'

# 查询任务 / 取消
curl http://127.0.0.1:8080/api/jobs/<job_id>
curl -X POST http://127.0.0.1:8080/api/jobs/<job_id>/cancel
```

### 8.4 视频与演员

```text
GET    /api/videos?complete=&favorite=&actress_id=&tag=&sort=
PATCH  /api/videos/{id}/metadata        {version, title, release_date, actresses, ...}
PATCH  /api/videos/{id}/favorite        {favorite}
POST   /api/videos/{id}/cover           上传封面
PUT    /api/videos/{id}/cover           {url}

GET    /api/actresses?complete=&favorite=&q=
GET    /api/actresses/{id}              详情 + 关联视频
PATCH  /api/actresses/{id}              编辑演员
DELETE /api/actresses/{id}              有关联视频时返回 409
PATCH  /api/actresses/{id}/favorite     {favorite}
POST/PUT /api/actresses/{id}/cover      上传 / URL 封面
```

刮削：

```text
POST /api/videos/{id}/scrape            {force, overwrite_manual} → {job_id}
POST /api/scrapes                       {root_id, force, overwrite_manual} → {job_id}
GET  /api/videos/{id}/scrape-logs       单个视频的逐源刮削日志
GET  /api/scrape-logs?video_id=&limit=  全局刮削日志
```

## 9. 数据目录与备份

默认数据目录：

- Windows：`%LOCALAPPDATA%\VBob`
- macOS：`~/Library/Application Support/VBob`
- Linux：`$XDG_DATA_HOME/vbob`（默认 `~/.local/share/vbob`）

可用 `--data-dir` 或环境变量 `VBOB_DATA_DIR` 覆盖。

```
<data-dir>/
  vbob.db
  covers/videos/
  covers/actresses/
  screenshots/
  logs/vbob.log
```

备份：停止服务后复制整个数据目录即可。数据库使用 WAL 模式，建议同时复制 `vbob.db-wal`、`vbob.db-shm`，或先停止服务再复制。

## 10. 常见问题

**扫描后没有视频**

- 文件可能小于默认的 50MB；通过 `PUT /api/settings` 调整 `scan.min_size_mb`。
- 检查扩展名是否在白名单中；隐藏文件、系统目录、被 `ignore_globs` 匹配的文件会被跳过。
- 文件必须位于已添加的扫描目录内，且扫描目录不能互相嵌套。

**目录改名后扫描不到视频**

在设置 → 目录管理 → 编辑路径中改为新地址。系统会按相对路径迁移已有记录，然后重新扫描。

**自动扫描没有触发**

- 检查该目录的自动扫描间隔是否为 0（关闭）。
- 服务需要保持运行；同一目录已有扫描任务时会跳过。
- 后台调度器每 30 秒检查一次，间隔建议至少 5 分钟。

**配置了刮削源但刮不到信息**

1. 打开视频详情，点击右上角刮削图标；或到设置 → 目录管理点击「批量刮削」。
2. 查看详情底部的「刮削日志」和页面顶部的任务提示，确认是 HTTP 错误、选择器为空、缺少占位符还是被反爬拦截。
3. 检查源类型与占位符是否匹配：`feature` 源需要番号（`{jav_code}` / `{code}`），`query` 源需要标题（`{title}`）。
4. CSS 选择器不支持 jQuery 的 `:contains()`，按文本匹配请使用 `xpath:`。
5. 标签、演员等多值字段需要在表达式末尾加 `| array`。
6. 服务端日志也会输出每次请求和失败原因（数据目录 `logs/vbob.log`）。

**演员只有姓名，没有生日/国籍/封面**

视频源只能抓到姓名时，需要：

1. 在视频源勾选「演员使用“姓名 + 演员页链接”提取」，让刮削记录演员详情页 URL；
2. 配置一个 `type: actress` 的演员资料源，请求 URL 使用 `{actress_url}`；
3. 重新刮削视频（更新演员链接），或在演员详情右上角点击刮削图标单独补全。

**视频显示「待补全」**

缺少名称、发行日期、演员、标签、本地封面或时长之一。打开详情 → 编辑补全即可。

**播放提示 `no_player`**

没有检测到播放器。安装 mpv/VLC/PotPlayer，或通过 API 指定 `playback.player.path` 后重试。

**播放提示 `path_outside_root` / `path_not_found`**

文件不在扫描目录内，或已被移动/删除。重新扫描或检查目录配置。

**删除演员返回 409**

该演员仍有关联视频。先删除视频记录（不会删除文件），或保留演员。

**封面保存失败**

只支持 jpeg/png/webp，单文件上限 10MB；URL 必须可访问且返回图片。

**端口被占用**

使用 `uv run vbob --port 8081` 换端口。

**如何重置**

停止服务，备份后删除数据目录中的 `vbob.db` 及 WAL 文件，重启会重新建库。此操作会清空扫描记录、设置、源配置、演员与收藏。

## 11. 当前限制与后续计划

- 批量刮削为顺序执行，尚未加入并发/断点续跑。
- 源配置暂未开放请求头、Cookies、超时/重试/限流等高级字段的图形化编辑（配置结构已预留，可通过 API 写入）。
- 源测试、SSE 实时进度、播放进度/继续观看尚未实现。
- 演员别名合并界面尚未实现；同名演员按规范化姓名去重。

## 12. 安全说明

- 默认只监听 `127.0.0.1`，不提供鉴权，请勿将服务暴露到局域网或公网。
- 用户自定义的刮削源 URL 由本机后端直接请求，存在访问任意地址的可能；只填写可信来源。
- 播放只接受由 `video_id` 解析出、且位于扫描目录内的文件路径。
