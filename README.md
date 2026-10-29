# VBob

本地视频管理器：扫描本地视频文件、通过可配置的刮削源获取元数据、在 Web 页面管理并调起本地播放器。

详细设计见 [doc/design.md](doc/design.md)。

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
- 视频列表/详情/删除 API
- 本机播放器探测与 `POST /api/videos/{id}/play`

前端：

- 海报墙（封面占位、番号/缺失标记、分页、搜索）
- 扫描目录管理、扫描进度、在库/缺失筛选
- 详情抽屉、元数据展示、播放与删除记录

尚未实现：刮削源执行引擎、封面缓存、元数据编辑、设置页、SSE 进度推送。
