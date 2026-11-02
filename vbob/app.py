"""FastAPI 应用装配。

职责：通过 lifespan 初始化数据库、存储、任务管理器与自动扫描调度器；
注册统一错误响应；优先挂载已构建的前端，否则返回占位页。
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api import router
from .config import default_data_dir
from .db import Database
from .errors import VBobError
from .jobs import JobManager
from .scheduler import ScanScheduler
from .store import Store

log = logging.getLogger(__name__)

# 前端未构建时（web/dist/index.html 不存在）展示的提示页。
PLACEHOLDER = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>VBob</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 720px; margin: 80px auto; padding: 0 24px; color: #222; }
    code { background: #f2f2f2; padding: 2px 6px; border-radius: 4px; }
    a { color: #2563eb; }
  </style>
</head>
<body>
  <h1>VBob 后端已启动</h1>
  <p>前端尚未构建。API 文档见 <a href="/docs">/docs</a>，健康检查见 <a href="/api/health">/api/health</a>。</p>
  <p>构建前端：<code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code>，然后重启服务。</p>
</body>
</html>"""


def _web_dist() -> Path:
    """返回前端构建产物目录。

    优先使用环境变量 ``VBOB_WEB_DIST``（便于打包或自定义部署），
    否则默认为仓库内的 ``web/dist``。
    """
    env = os.environ.get("VBOB_WEB_DIST")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parent.parent / "web" / "dist"


def create_app(
    data_dir: Path | None = None, *, seed_defaults: bool = True
) -> FastAPI:
    """创建并配置 FastAPI 应用。

    参数:
        data_dir: 数据目录；为 ``None`` 时使用 :func:`vbob.config.default_data_dir`。
        seed_defaults: 首次启动是否写入预置刮削源；测试中可关闭以避免联网。

    返回:
        已注册路由、异常处理器与前端静态资源的应用实例。
    """
    resolved_data_dir = (data_dir or default_data_dir()).resolve()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """应用启动时按依赖顺序初始化资源，关闭时停止调度器。"""
        resolved_data_dir.mkdir(parents=True, exist_ok=True)
        for name in ("covers", "covers/videos", "covers/actresses", "screenshots", "logs"):
            (resolved_data_dir / name).mkdir(parents=True, exist_ok=True)
        # 先完成数据库迁移，再让 Store 访问表结构。
        db = Database(resolved_data_dir / "vbob.db")
        db.migrate()
        store = Store(db)
        # 升级兼容：先补齐旧数据的剧集特征，再把重复番号/剧集记录合并为影片分组。
        backfilled = store.backfill_episode_features()
        if backfilled:
            log.info("backfilled episode features for %s videos", backfilled)
        merged = store.merge_duplicate_videos()
        if merged:
            log.info("merged %s duplicate video rows into groups", merged)
        if seed_defaults:
            seeded = store.seed_default_sources()
            if seeded:
                log.info("seeded %s default scrape sources", seeded)
        jobs = JobManager(store)
        # 上次进程退出时残留的 running 任务无法继续，统一标记为失败。
        jobs.recover()
        # 调度器依赖已恢复的任务状态，因此放在 recover 之后启动。
        scheduler = ScanScheduler(store, jobs)
        scheduler.start()
        # 挂到 app.state，供各路由通过 request.app.state 读取。
        app.state.db = db
        app.state.store = store
        app.state.jobs = jobs
        app.state.scheduler = scheduler
        app.state.data_dir = resolved_data_dir
        log.info("VBob ready, data dir: %s", resolved_data_dir)
        try:
            yield
        finally:
            # 只停止调度线程；进行中的任务线程为守护线程，随进程退出。
            scheduler.stop()

    app = FastAPI(title="VBob", version=__version__, lifespan=lifespan)
    app.state.data_dir = resolved_data_dir

    # 仅放行 Vite 开发服务器；生产环境前端与后端同源，无需 CORS。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 必须先注册 API 路由；后面的 "/" 静态挂载会兜底其余路径。
    app.include_router(router)

    @app.exception_handler(VBobError)
    async def vobob_error_handler(request: Request, exc: VBobError) -> JSONResponse:
        """把业务异常转换为统一错误信封，状态码与 code 由异常类决定。"""
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}},
            status_code=exc.status,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """请求体/查询参数校验失败：固定返回 422 与字段级 details。"""
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_request",
                    "message": "参数校验失败",
                    "details": jsonable_encoder(exc.errors()),
                }
            },
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """将框架抛出的 HTTPException（如 404/405）也包装成统一错误信封。"""
        message = exc.detail if isinstance(exc.detail, str) else "请求失败"
        return JSONResponse(
            {"error": {"code": f"http_{exc.status_code}", "message": message}},
            status_code=exc.status_code,
        )

    dist = _web_dist()
    # 只有前端确实构建过才挂载；html=True 让目录请求回退到 index.html。
    if (dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    else:
        @app.get("/", include_in_schema=False)
        def placeholder() -> HTMLResponse:
            """前端未构建时返回引导页，不影响 /api 与 /docs 使用。"""
            return HTMLResponse(PLACEHOLDER)

    return app
