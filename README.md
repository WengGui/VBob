# VBob

本地视频管理器：扫描本地视频文件、通过可配置的刮削源获取元数据、在 Web 页面管理并调起本地播放器。

使用说明见 [doc/usage.md](doc/usage.md)，详细设计见 [doc/design.md](doc/design.md)。

## 开发

需要 Python 3.12+ 与 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync --extra dev

# 构建前端（首次或前端改动后）
cd web
npm install
npm run build
cd ..

uv run vbob --open
```

前端开发模式（Vite 代理 `/api` 到 8080）：

```bash
cd web && npm run dev   # http://127.0.0.1:5173
uv run vbob             # 另一个终端
```

默认数据目录：

- Windows：`%LOCALAPPDATA%\VBob`
- macOS：`~/Library/Application Support/VBob`
- Linux：`$XDG_DATA_HOME/vbob`（默认 `~/.local/share/vbob`）

可用 `--data-dir` 或环境变量 `VBOB_DATA_DIR` 覆盖。

启动后：

- Web UI：<http://127.0.0.1:8080/>（前端未构建时显示占位页）
- API 文档：<http://127.0.0.1:8080/docs>
- 健康检查：<http://127.0.0.1:8080/api/health>

## 测试

```bash
uv run pytest
```

## 当前进度

后端 MVP 第一块：

- SQLite schema 与版本化迁移
- 扫描目录管理、异步扫描任务（进度/取消/增量/缺失标记）
- 文件名特征提取（番号、标题、年份）
- 视频列表/详情/删除 API，全字段手动编辑、收藏、封面本地存储
- 演员实体、视频-演员关联、演员 CRUD / 收藏 / 封面 / 删除保护
- 完整度计算（视频 / 演员独立）
- 目录自动扫描间隔、扫描统计、修改目录路径时按相对路径迁移记录
- 本机播放器探测与 `POST /api/videos/{id}/play`
- 刮削源配置 CRUD 与校验（feature / query / actress 三类）
- 刮削引擎：HTTP 抓取、编码探测、css/xpath/json/regex 提取、多源合并、封面下载
- 单视频刮削、按目录批量刮削、逐源刮削日志与任务进度
- 演员资料源刮削与自动补全

前端：

- 左侧菜单：视频、演员、收藏（视频/演员）、主题、设置
- 视频/演员海报墙，展示必填信息与完整度；收藏按钮
- 视频与演员详情抽屉、全字段编辑弹窗、封面上传/URL、单视频刮削与刮削日志
- 不可拖动的设置弹窗：目录管理（统计、自动扫描间隔、编辑路径、手动扫描、批量刮削）、播放器、图形化刮削源
- 浅色/深色主题、扫描/刮削进度、搜索排序与分页

尚未实现：源配置测试按钮、请求头/Cookies 等高级字段的图形化编辑、SSE 实时进度、播放进度/继续观看、演员别名合并界面。
