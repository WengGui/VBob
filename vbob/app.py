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
from .store import Store

log = logging.getLogger(__name__)

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
    env = os.environ.get("VBOB_WEB_DIST")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parent.parent / "web" / "dist"


def create_app(data_dir: Path | None = None) -> FastAPI:
    resolved_data_dir = (data_dir or default_data_dir()).resolve()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved_data_dir.mkdir(parents=True, exist_ok=True)
        for name in ("covers", "screenshots", "logs"):
            (resolved_data_dir / name).mkdir(exist_ok=True)
        db = Database(resolved_data_dir / "vbob.db")
        db.migrate()
        store = Store(db)
        jobs = JobManager(store)
        jobs.recover()
        app.state.db = db
        app.state.store = store
        app.state.jobs = jobs
        app.state.data_dir = resolved_data_dir
        log.info("VBob ready, data dir: %s", resolved_data_dir)
        yield

    app = FastAPI(title="VBob", version=__version__, lifespan=lifespan)
    app.state.data_dir = resolved_data_dir

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    @app.exception_handler(VBobError)
    async def vobob_error_handler(request: Request, exc: VBobError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}},
            status_code=exc.status,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
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
        message = exc.detail if isinstance(exc.detail, str) else "请求失败"
        return JSONResponse(
            {"error": {"code": f"http_{exc.status_code}", "message": message}},
            status_code=exc.status_code,
        )

    dist = _web_dist()
    if (dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    else:
        @app.get("/", include_in_schema=False)
        def placeholder() -> HTMLResponse:
            return HTMLResponse(PLACEHOLDER)

    return app
