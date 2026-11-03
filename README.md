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

默认数据目录为启动时当前工作目录下的 `data/`（即项目根目录的 `data/`，已加入 `.gitignore`）。

可用 `--data-dir` 或环境变量 `VBOB_DATA_DIR` 覆盖：

```bash
uv run vbob --data-dir D:\VBobData
set VBOB_DATA_DIR=D:\VBobData    # Windows；bash 用 export
```

启动后：

- Web UI：<http://127.0.0.1:8080/>（前端未构建时显示占位页）
- API 文档：<http://127.0.0.1:8080/docs>
- 健康检查：<http://127.0.0.1:8080/api/health>

## 打包为 Windows 可执行文件

需要构建机安装 Python/uv 和 Node.js；目标机器不需要 Python、Node 或 uv。

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

产物：

- `dist\VBob.exe`：单文件程序（约 25MB）；
- `dist\VBob-windows-x64.zip`：分发包。

使用方式：把 exe 解压到任意**可写目录**（例如 `D:\VBob` 或桌面），双击 `VBob.exe`。

- 首次运行会在 exe 同目录创建 `data\`，保存数据库、封面和日志，并自动打开浏览器；
- 默认写入两个可编辑的刮削源；
- 控制台窗口需要保持打开，关闭窗口即停止服务；
- 迁移数据：把旧机器的 `data\` 整个复制到新机器的 exe 同目录即可；
- 升级：覆盖 exe，保留 `data\`，数据库迁移会自动执行。

常用参数：

```text
VBob.exe --port 8081       # 换端口
VBob.exe --no-open         # 不自动打开浏览器
VBob.exe --data-dir D:\VBobData
```

exe 未签名，Windows SmartScreen 可能提示；选择“更多信息 → 仍要运行”。不要把 exe 放在 `Program Files` 等无写权限目录。

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
- 视频详情弹窗（固定尺寸平铺布局）与演员详情抽屉、字段级编辑、封面上传/URL、单视频重新刮削；手动修正番号会用于后续刮削
- 同番号多文件、剧集文件自动合并为一部影片，播放时选择具体文件；纯集数文件名使用文件夹名作为标题
- 海报墙支持拖动合并剧集，编辑弹窗也可手动归入其他剧集；详情页可把文件移出剧集撤销误合并
- 海报墙可一键筛选「待补全」和「未刮削」视频
- 删除支持“仅删记录”或“彻底删除文件”，多文件可勾选删除
- 海报墙随机排序、演员/标签/系列点击筛选、可折叠标签行
- 视频详情固定尺寸平铺展示，演员/标签/系列可直接触发筛选
- 删除目录可选保留或删除磁盘文件；默认刮削源首次启动自动写入
- 不可拖动的设置弹窗：目录管理（统计、自动扫描间隔、编辑路径、手动扫描、批量刮削）、本地播放器选择、图形化刮削源
- 浅色/深色主题、扫描/刮削进度、搜索排序与分页

尚未实现：源配置测试按钮、请求头/Cookies 等高级字段的图形化编辑、SSE 实时进度、播放进度/继续观看、演员别名合并界面。
