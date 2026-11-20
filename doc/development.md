# VBob 开发指南

> 面向二次开发与贡献者。功能使用说明见 [usage.md](usage.md)，架构与数据模型见 [design.md](design.md)。

## 1. 环境准备

| 依赖 | 版本 | 说明 |
| --- | --- | --- |
| Python | 3.12+ | 后端与测试 |
| [uv](https://docs.astral.sh/uv/) | 最新 | 依赖与虚拟环境管理 |
| Node.js | 20+（建议 22） | 前端构建与测试 |
| PowerShell | 5.1+ | 仅 Windows 打包需要 |

```bash
git clone git@github.com:WengGui/VBob.git
cd VBob
uv sync --extra dev          # 后端依赖 + pytest
cd web && npm install && cd ..
```

## 2. 本地开发

```bash
# 后端（默认 http://127.0.0.1:8080，自动读取 ./data）
uv run vbob --open

# 前端热更新（Vite 把 /api 代理到 8080）
cd web && npm run dev        # http://127.0.0.1:5173
```

后端改动需要重启 `uv run vbob`；前端改动热更新即可。只改后端、想用已构建的页面时，先 `cd web && npm run build`。

常用命令：

```bash
uv run pytest                # 后端全部测试
uv run pytest tests/test_scraper.py -q
cd web && npm test           # 前端纯函数测试（vitest）
cd web && npm run build      # 类型检查 + 生产构建
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1   # 打包 exe + zip
```

## 3. 代码结构速查

| 路径 | 职责 |
| --- | --- |
| `vbob/api.py` | HTTP 路由、参数校验、错误映射；图片接口的缓存头与越界校验 |
| `vbob/app.py` | FastAPI 装配、生命周期、异常处理、静态资源挂载 |
| `vbob/scraper.py` | 源解析、字段合并、封面下载、演员补全、批量并发 |
| `vbob/probe.py` | 源连通性检测（信号格数） |
| `vbob/http_utils.py` | 浏览器请求头、占位符填充、Cookie 解析 |
| `vbob/images.py` | 图片下载、格式校验、本地落盘 |
| `vbob/source_templates.py` / `default_sources.py` | 内置模板 / 首次启动默认源 |
| `vbob/store/` | 数据访问层，按领域拆分为多个 mixin，`Store` 为门面 |
| `vbob/migrations/` | 版本化 SQL 迁移 |
| `web/src/` | 前端；`components/` 组件、`hooks/` 数据加载、`view.ts` 共享常量 |
| `tests/` | 后端测试；前端测试与被测文件同目录（`*.test.ts`） |

新增一个业务接口的典型路径：`schemas.py` 定义请求体 → `store/` 中实现 SQL → `api.py` 暴露路由 → `web/src/api.ts` 增加方法 → 组件调用。

## 4. 数据与迁移

- 迁移文件命名为 `000N_描述.sql`，按文件名排序依次执行，应用过的版本记录在 `schema_migrations`。
- **不要修改已发布的迁移文件**：旧库不会重新执行它。需要变更时新增 `000N+1_xxx.sql`。
- 已有数据的库在应用新迁移前会自动备份到 `data/backups/vbob-<时间>.db`，保留 5 份；全新库不备份。
- 迁移 SQL 与版本记录在同一事务中执行；失败会回滚并阻止启动，避免半迁移状态。
- 修改表结构时同步更新：迁移文件、`store/` 中相关读写、`doc/design.md` 第 3/15 节、必要时补测试。

本地验证迁移是否可用：

```bash
# 复制一份真实数据库到临时目录后执行，避免动到正式数据
cp data/vbob.db /tmp/vbob-test.db
uv run python -c "from pathlib import Path; from vbob.db import Database; Database(Path('/tmp/vbob-test.db')).migrate()"
```

## 5. 测试

### 5.1 后端

- 测试通过 `create_app(tmp_path / 'data', seed_defaults=False)` 使用隔离数据目录，不会读写仓库里的 `data/`。
- 扫描类测试先 `PUT /api/settings` 把 `scan.min_size_mb` 调为 0，再创建目录、写文件、`POST /api/scans` 并轮询任务。
- 刮削类测试使用 `tests/test_scraper.py` 中的 `ThreadingHTTPServer` 模拟站点，覆盖 HTML/JSON/GraphQL、详情请求、封面前缀、源顺序与失败场景。
- 涉及网络的逻辑优先 mock（如 `vbob.images._fetch_once`），不要把测试绑到真实站点。

### 5.2 前端

- `npm test` 运行 vitest，当前覆盖 `format.ts` 等纯函数；纯逻辑尽量抽成无副作用函数后再测。
- 组件行为通过 `npm run build` 的类型检查兜底，`noUnusedLocals` 开启，未使用的变量会直接报错。

### 5.3 CI

- push master 或提交 PR：后端 Windows 跑 pytest，前端 Ubuntu 跑构建与单测。
- 推送 `v*` 标签：Release 工作流先跑测试，通过后才构建并上传 exe/zip。

## 6. 调试

- **日志**：`data/logs/vbob.log`（2MB 滚动，保留 3 份），启动与非回环监听警告也写在这里。
- **刮削排查**：视频详情 →「刮削日志」查看每个源的请求结果；源配置错误会在保存时返回 422 并指出字段。
- **任务状态**：`GET /api/jobs/{id}`；界面顶部任务条可取消扫描/刮削。
- **源连通性**：设置 → 刮削源点击信号条，或在详情页看错误信息；检测只请求站点根路径，失败不代表具体接口不可用。
- **API 文档**：服务启动后访问 <http://127.0.0.1:8080/docs>。
- **抓包/复现**：可把源配置的 `request.timeout_ms` 调小、`rate_limit.qps` 调低，减少等待。

## 7. 发布流程

1. 确认 `uv run pytest` 与 `cd web && npm test && npm run build` 全部通过。
2. 同步版本号（五处）：`pyproject.toml`、`vbob/__init__.py`、`web/package.json`、`web/package-lock.json`（两处）、`uv.lock` 中 `name = "vbob"` 条目。
3. 更新 `README.md` 更新日志与 `doc/usage.md` 适用版本。
4. 本地打包验证：`scripts\build_windows.ps1`，用 `dist\VBob.exe --port 8081 --data-dir <临时目录>` 冒烟。
5. 提交后推送 master，再打标签：

```bash
git tag v0.4.0
git push origin master
git push origin v0.4.0
```

GitHub Actions 会构建并创建 Release，产物为 `VBob.exe` 与 `VBob-windows-x64.zip`。

> 打包机若使用国内 PyPI 镜像，`uv sync` 可能把 `uv.lock` 的下载地址改写成镜像地址，提交前检查并还原（`git checkout -- uv.lock`）。

## 8. 代码约定

- 所有公开函数/方法写中文 docstring，说明职责与关键边界；注释解释“为什么”，不复述代码。
- 业务错误统一抛 `vbob.errors` 中的类型（`InvalidError` / `NotFoundError` / `ConflictError` / `PlaybackError`），由 `app.py` 转成 `{"error": {"code", "message"}}`。
- 跨表写入放在 `Database.transaction()` 中；单条读写用 `database.connection()`。
- 用户手动编辑过的字段由 `metadata.manual_fields` 保护，刮削默认不覆盖。
- 日志中不要打印 API 密钥、完整请求 URL（可能含密钥）或用户文件内容。
- 前端组件保持“展示 + 上报事件”，数据加载集中在 `hooks/`，共享类型放在 `api.ts`。

## 9. 常见问题

**`uv run pytest` 报 `Scripts/vbob.exe` 被占用**

正在运行的 `uv run vbob`（或 `vbob.exe`）占用了虚拟环境入口，先停止服务再执行。

**端口 8080 被占用**

`uv run vbob --port 8081`，或关闭占用进程。

**目录选择框没有弹出**

目录选择依赖系统对话框（Windows PowerShell / macOS osascript / Linux zenity），远程或无桌面环境会失败，可直接手填路径。

**构建时拉了镜像源**

见第 7 节最后一条：检查 `uv.lock` 是否被改写并还原。
