<p align="center">
  <img src="doc/vbob_icon.png" width="120" alt="VBob">
</p>

<h1 align="center">VBob</h1>

<p align="center">
  本地优先的视频库管理器：扫描、刮削、整理、播放，一个页面搞定。
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white">
  <img alt="React" src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white">
  <img alt="Platform" src="https://img.shields.io/badge/Windows-x64-0078D4?logo=windows&logoColor=white">
  <a href="https://github.com/WengGui/VBob/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/WengGui/VBob/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="License" src="https://img.shields.io/badge/License-MIT-green">
</p>

## 简介

VBob 是一个**完全本地运行**的视频库管理工具。它扫描你指定的目录，从文件名中提取番号、标题、年份和集数，通过可配置的刮削源补全元数据，最后以海报墙的形式浏览、筛选和播放。

- **本地优先**：数据库、封面、日志都保存在本机 `data/`，不需要账号或云服务；
- **开箱即用**：Windows 用户下载解压后双击 `VBob.exe` 即可，无需安装 Python 或 Node.js；
- **可自由扩展**：刮削源支持 CSS、XPath、JSON、正则等提取方式，可在界面中配置；
- **自带播放器联动**：调用本机 mpv、VLC、PotPlayer 等播放，支持多文件选择。

> VBob 不提供、不分发任何视频内容，也不内置第三方站点凭据。请仅管理你有权访问的媒体文件，并遵守所在地法律法规。

## 功能

**扫描与整理**

- 多目录扫描、增量扫描、按目录设置自动扫描间隔；
- 添加目录时可直接调用系统目录选择框，并一次配置媒体类型、限定源和扫描间隔；
- 按媒体类型（电影 / 动漫 / 剧集 / JAV / 其他）组织视频，左侧菜单可折叠分类，筛选与乱序只在当前分类内生效；
- 识别番号、标题、年份、分辨率、有码/无码等特征；
- 同一番号的多文件（A/B 分段、不同清晰度）自动合并为一部影片，播放时再选文件；
- 自动识别剧集（`第3集`、`第三集`、`EP03`、`S01E03`、`片名3` 等），支持手动合并、拖动合并与移出剧集；
- 扫描目录路径可编辑，支持目录收窄/扩大的记录迁移。

**刮削与演员**

- 视频源、查询源、演员源三类刮削源，图形化配置字段提取规则；
- 内置 **TMDB**（电影/剧集/动漫）、**Shikimori**（动漫）与 **ThePornDB**（欧美成人）源模板，一键添加；
- 每个源可一键检测网络连通性，用手机信号式的 5 格信号条显示域名可达性与响应速度；
- 目录可按顺序限定源；视频详情可切换并记住偏好源，支持覆盖式重刮；
- 支持二次详情请求、源级变量与封面 CDN 前缀，适配 TMDB、Shikimori 等 JSON API；
- 多源合并、封面下载、逐源日志、单视频重刮、按目录批量刮削（并发数可调）；
- 封面下载自动重试并支持多尺寸兜底，失败后可在详情页一键「重新下载封面」；
- 删除影片/演员时同步清理本地封面，启动时清理数据库不再引用的孤儿图片；
- 手动修正番号后会用于后续刮削，重新扫描不会覆盖已修正的信息；
- 演员独立资料页、作品数统计、收藏与封面管理。

**浏览与播放**

- 视频 / 演员 / 收藏海报墙，左侧按媒体类型分组并显示数量，深色与浅色主题；
- 按演员、标签、系列筛选，支持「待补全」「未刮削」和随机排序；
- 视频详情支持全字段编辑、封面本地上传或 URL、完整度提示；
- 调用本地播放器，多文件时弹窗选择具体文件；
- 删除时可选择仅删记录或同时删除磁盘文件。

## 下载

前往 **[GitHub Releases](https://github.com/WengGui/VBob/releases/latest)** 下载最新版本。每个 Release 同时提供：

| 文件 | 说明 |
| --- | --- |
| `VBob-windows-x64.zip` | **推荐**，解压后双击 `VBob.exe` |
| `VBob.exe` | Windows x64 单文件程序 |

### Windows 使用步骤

1. 下载 `VBob-windows-x64.zip` 并解压到**可写目录**，例如 `D:\VBob`；
2. 双击 `VBob.exe`，首次运行会自动创建 `data\` 并打开浏览器；
3. 在左下角「设置 → 目录管理」中添加视频目录，然后点击「扫描全部」；
4. 扫描完成后即可在海报墙浏览视频，点击卡片查看详情或播放。

> 不要放在 `Program Files` 等无写权限目录。exe 未签名，Windows SmartScreen 提示时选择「更多信息 → 仍要运行」。

### 数据、升级与迁移

- 数据库、封面和日志保存在 `VBob.exe` 同目录的 `data\`；
- **升级**：关闭程序，替换 `VBob.exe`，保留 `data\`，数据库会自动迁移；
- **迁移到新电脑**：把整个 `data\` 复制到新电脑的 exe 同目录；
- 也可以指定其他数据目录：`VBob.exe --data-dir D:\VBobData`。

### 常用启动参数

```text
VBob.exe --port 8081       # 8080 被占用时换端口
VBob.exe --no-open         # 不自动打开浏览器
VBob.exe --data-dir PATH   # 指定数据目录
VBob.exe --help            # 查看全部参数
```

关闭控制台窗口即停止服务。

## 从源码运行

需要 Python 3.12+、[uv](https://docs.astral.sh/uv/) 和 Node.js 20+。

```bash
git clone git@github.com:WengGui/VBob.git
cd VBob

uv sync --extra dev

cd web
npm install
npm run build
cd ..

uv run vbob --open
```

启动后访问 <http://127.0.0.1:8080>。API 文档在 <http://127.0.0.1:8080/docs>。

前端开发模式（Vite 会将 `/api` 代理到 8080）：

```bash
cd web && npm run dev   # http://127.0.0.1:5173
uv run vbob             # 另一个终端
```

运行测试：

```bash
uv run pytest
cd web && npm test   # 前端纯函数测试
```

推送分支或提交 PR 时，GitHub Actions 会运行后端测试和前端构建/测试。

## 打包 Windows 版

在 Windows 构建机上执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

脚本会安装依赖、构建前端并调用 PyInstaller，产物为：

- `dist\VBob.exe`
- `dist\VBob-windows-x64.zip`

推送 `v*` 标签时，GitHub Actions 会自动构建并创建 Release，上传 exe 和 zip：

```bash
git tag v0.1.0
git push origin v0.1.0
```

图标源文件为 `doc/vbob_icon.png`，修改后运行 `uv run --with pillow python scripts/make_icons.py` 重新生成网站 favicon 与 `assets/vbob.ico`。

## 文档

| 文档 | 内容 |
| --- | --- |
| [doc/usage.md](doc/usage.md) | 完整使用说明：目录、扫描、刮削、源模板、连通性检测、API 与 FAQ |
| [doc/design.md](doc/design.md) | 架构、数据模型、源配置格式、调度与 v0.6 增量设计 |
| [doc/development.md](doc/development.md) | 开发指南：环境、代码结构、测试、调试与发布流程 |
| [doc/数据迁移SQL.md](doc/数据迁移SQL.md) | 旧库升级到媒体分类版本的 SQL 与回滚说明 |

## 第三方元数据

设置 → 刮削源 → 「从模板添加」可创建以下源：

| 模板 | 媒体类型 | 用途 | 需要配置 |
| --- | --- | --- | --- |
| javBus | JAV | 番号、标题、发行日期、演员、标签、封面、时长、厂商 | 无 |
| javBusActress | JAV | 演员生日、身高、三围、罩杯、封面 | 无 |
| TMDB 电影 | 电影 | 中文名、原名、简介、海报、时长、类型、导演 | TMDB API Key（v3） |
| TMDB 剧集 | 剧集 | 中文名、原名、简介、海报、类型、制作公司 | TMDB API Key（v3） |
| TMDB 动漫 | 动漫 | 中文名、原名、简介、海报、类型、制作公司 | TMDB API Key（v3） |
| Shikimori 动漫 | 动漫 | 原名、海报、类型、制作公司 | 无 |
| ThePornDB | 其他 | 欧美成人影片/场景的标题、日期、简介、封面、片商、演员 | ThePornDB API Token |

- TMDB 密钥在 <https://www.themoviedb.org/settings/api> 申请，只保存在本地数据库；
- ThePornDB 使用 GraphQL 接口，Token 在 <https://theporndb.net/user/api-tokens> 生成（只显示一次）；
- 模板使用 `api.tmdb.org`，部分网络下 `api.themoviedb.org` 会被 DNS 污染；
- 本项目使用 TMDB API，但未获得 TMDB 的认可或认证（This product uses the TMDB API but is not endorsed or certified by TMDB）；
- Shikimori 数据来自 <https://shikimori.one>，限速 1 次/秒；
- 请遵守各站点的使用条款，仅将元数据用于个人用途。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | Python 3.12+、FastAPI、Pydantic、SQLite（WAL + 版本化迁移） |
| 抓取 | httpx、parsel、jmespath、charset-normalizer |
| 前端 | React 19、Vite、TypeScript、Tailwind CSS 4 |
| 打包 | PyInstaller（Windows 单文件） |

## 项目结构

```text
vbob/                后端：API、扫描、刮削、连通性检测、存储、播放器
vbob/store/          数据访问层：按领域拆分的 mixin，Store 为统一门面
vbob/migrations/     SQLite 迁移脚本（0001-0006）
web/                 前端：React + Vite
web/src/components/  界面组件（侧栏、弹窗、信号条、海报卡等）
web/src/hooks/       数据加载 hook
web/public/          网站图标等静态资源
tests/               后端测试（前端测试与被测文件放在一起）
scripts/             构建与图标生成脚本
doc/                 使用、设计、开发与迁移文档
assets/              exe 图标
```

## 数据与隐私

- 默认只监听 `127.0.0.1`，不对外提供访问；
- 没有账号体系、遥测或云端同步；
- 仅在刮削时向**你配置的**刮削源发送番号、标题等查询信息；
- 请勿将 `--host` 改为 `0.0.0.0` 暴露到公网；
- 备份或迁移时复制整个 `data/` 目录即可。

## 常见问题

**端口 8080 被占用怎么办？**

使用 `VBob.exe --port 8081`，或关闭占用端口的程序。

**提示找不到播放器？**

在「设置 → 播放器」中选择 mpv、VLC、PotPlayer，或手动指定可执行文件路径。

**重新扫描后手动修改的番号会被覆盖吗？**

不会。手动编辑的字段会保留，并用于后续刮削匹配。

**刮削成功了，但海报是空的/还是旧图？**

一般是封面图片下载时被 CDN 重置，或浏览器缓存了旧图。打开视频详情点「重新下载封面」即可；换源后前端会自动刷新封面地址。

**支持 macOS / Linux 吗？**

后端与前端可以在源码模式下运行，目前只提供 Windows 打包产物。

## 更新日志

### 未发布

- 内置模板新增 javBus / javBusActress（与首次启动的默认源一致），删除后可一键重新添加；
- 批量刮削支持并发（`scraping.workers`，默认 3），并复用一次任务内的源/目录配置；
- 删除影片或演员时同步删除本地封面，启动时清理数据库不再引用的孤儿图片；
- 数据库升级前自动备份到 `data/backups/`，最多保留 5 份；
- 封面接口改为轻量查询，带版本参数的图片可长期缓存；
- 图片下载与刮削统一使用 httpx，并遵循源配置的代理；
- 前端拆分侧栏、列表加载 hook 与通用组件，弹窗支持 Esc 关闭与焦点管理，新增根级错误页；
- 新增 GitHub Actions CI（后端测试 + 前端构建/测试），发布前强制跑测试。

### v0.3.0

- 刮削源支持网络连通性检测：单个或一键检测全部源，用 5 格信号条按响应耗时显示网络质量；
- 新增 ThePornDB 源模板，刮削引擎支持 POST JSON 请求体与请求头占位符；
- 数据迁移到 `0006`，保存每个源最近一次检测结果。

### v0.2.0

- 新增媒体类型（电影 / 动漫 / 剧集 / JAV / 其他），左侧菜单可折叠分类，列表和筛选按分类生效；
- 目录支持指定媒体类型和有序的限定源；添加目录改为完整弹窗，可直接调用系统目录选择框；
- 视频详情显示实际来源列表，可切换并记住偏好源，支持覆盖式重刮；
- 内置 TMDB（电影/剧集/动漫）与 Shikimori（动漫）源模板；
- 刮削引擎支持二次详情请求、源级变量、封面 CDN 前缀；
- 封面下载重试、尺寸兜底和「重新下载封面」按钮；
- 数据迁移到 `0005`，旧库自动归类为 JAV，可在界面中调整。

### v0.1.0

- 首个公开版本：扫描、刮削源配置、演员资料、海报墙与本地播放。

## 参与贡献

欢迎提交 Issue 和 Pull Request。提交前请确保：

- `uv run pytest` 全部通过；
- `cd web && npm test && npm run build` 通过（构建含 TypeScript 检查）；
- 代码风格与现有实现保持一致，并补充必要的测试。

开发环境、代码结构、调试与发布流程详见 [doc/development.md](doc/development.md)。

## License

本项目基于 [MIT License](LICENSE) 开源。
