from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import FileResponse

from . import __version__
from .errors import InvalidError, NotFoundError, PlaybackError
from .extractors import FeaturePipeline
from .jobs import JobManager
from .paths import is_within, path_key
from .player import launch, players_payload, resolve_player
from .scanner import Scanner, ScanOptions
from .schemas import (
    PlayRequest,
    ScanRequest,
    ScanRootCreate,
    ScanRootUpdate,
    SourceStateUpdate,
)
from .store import SORT_ORDERS, Store

router = APIRouter(prefix="/api")

SCRAPE_STATUSES = {"pending", "scraping", "success", "failed", "no_match", "skipped_manual"}


def _store(request: Request) -> Store:
    return request.app.state.store


def _jobs(request: Request) -> JobManager:
    return request.app.state.jobs


@router.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "version": __version__}


# --------------------------------------------------------------------- settings


@router.get("/settings")
def get_settings(request: Request) -> dict[str, Any]:
    return _store(request).get_settings()


@router.put("/settings")
def update_settings(request: Request, patch: dict[str, Any]) -> dict[str, Any]:
    return _store(request).update_settings(patch)


# -------------------------------------------------------------------- scan roots


@router.get("/scan-roots")
def list_roots(request: Request) -> dict[str, Any]:
    return {"items": _store(request).list_roots()}


@router.post("/scan-roots", status_code=201)
def create_root(request: Request, body: ScanRootCreate) -> dict[str, Any]:
    return _store(request).create_root(body.path, body.enabled)


@router.put("/scan-roots/{root_id}")
def update_root(request: Request, root_id: int, body: ScanRootUpdate) -> dict[str, Any]:
    return _store(request).update_root(root_id, enabled=body.enabled)


@router.delete("/scan-roots/{root_id}", status_code=204)
def delete_root(request: Request, root_id: int) -> Response:
    _store(request).delete_root(root_id)
    return Response(status_code=204)


# ------------------------------------------------------------------------ scans


@router.post("/scans", status_code=202)
def create_scan(request: Request, body: ScanRequest) -> dict[str, Any]:
    store = _store(request)
    if body.root_id is not None:
        store.get_root(body.root_id)
        root_ids = [body.root_id]
    else:
        root_ids = [root["id"] for root in store.list_roots(enabled_only=True)]
        if not root_ids:
            raise InvalidError("没有启用的扫描目录")

    def run_scan(job_id: str, cancel_event, progress) -> None:
        settings = store.get_settings()
        options = ScanOptions.from_settings(settings)
        pipeline = FeaturePipeline(settings["scraping"]["clean_rules"])
        scanner = Scanner(
            store,
            options,
            pipeline=pipeline,
            cancel_event=cancel_event,
            progress=progress,
        )
        summary = scanner.run(root_ids, full=body.full)
        message = (
            f"完成：新增 {summary.added}，更新 {summary.updated}，"
            f"未变 {summary.unchanged}，缺失 {summary.missing}，失败 {summary.failed}"
        )
        if summary.errors:
            message += f"；首个错误：{summary.errors[0]}"
        progress(
            done=summary.total,
            total=summary.total,
            failed=summary.failed,
            message=message,
        )

    job_id = _jobs(request).start(
        "scan", {"root_ids": root_ids, "full": body.full}, run_scan
    )
    return {"job_id": job_id}


@router.get("/scans/{job_id}")
def get_scan_job(request: Request, job_id: str) -> dict[str, Any]:
    return _store(request).get_job(job_id)


# ------------------------------------------------------------------------- jobs


@router.get("/jobs")
def list_jobs(request: Request, limit: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    return {"items": _store(request).list_jobs(limit)}


@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str) -> dict[str, Any]:
    return _store(request).get_job(job_id)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(request: Request, job_id: str) -> dict[str, Any]:
    return _jobs(request).cancel(job_id)


# ---------------------------------------------------------------------- sources


@router.get("/sources")
def list_sources(request: Request) -> dict[str, Any]:
    return {"items": _store(request).list_sources()}


@router.post("/sources", status_code=201)
def create_source(request: Request, config: dict[str, Any]) -> dict[str, Any]:
    return _store(request).create_source(config)


@router.put("/sources/{source_id}")
def update_source(request: Request, source_id: int, config: dict[str, Any]) -> dict[str, Any]:
    return _store(request).update_source(source_id, config)


@router.patch("/sources/{source_id}")
def update_source_state(
    request: Request, source_id: int, body: SourceStateUpdate
) -> dict[str, Any]:
    return _store(request).update_source_state(
        source_id, enabled=body.enabled, priority=body.priority
    )


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(request: Request, source_id: int) -> Response:
    _store(request).delete_source(source_id)
    return Response(status_code=204)


# ----------------------------------------------------------------------- videos


@router.get("/videos")
def list_videos(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    q: str | None = None,
    has_code: bool | None = None,
    scrape_status: str | None = None,
    present: bool | None = None,
    sort: str = "updated_at",
) -> dict[str, Any]:
    if sort not in SORT_ORDERS:
        raise InvalidError(f"不支持的排序方式: {sort}")
    if scrape_status is not None and scrape_status not in SCRAPE_STATUSES:
        raise InvalidError(f"不支持的刮削状态: {scrape_status}")
    items, total = _store(request).list_videos(
        page=page,
        page_size=page_size,
        q=q,
        has_code=has_code,
        scrape_status=scrape_status,
        present=present,
        sort=sort,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/videos/{video_id}")
def get_video(request: Request, video_id: int) -> dict[str, Any]:
    return _store(request).get_video(video_id)


@router.delete("/videos/{video_id}", status_code=204)
def delete_video(request: Request, video_id: int) -> Response:
    _store(request).delete_video(video_id)
    return Response(status_code=204)


@router.get("/videos/{video_id}/cover")
def get_cover(request: Request, video_id: int) -> FileResponse:
    detail = _store(request).get_video(video_id)
    metadata = detail["metadata"] or {}
    path = _data_file(request, metadata.get("cover_local"))
    return FileResponse(path)


@router.get("/videos/{video_id}/screenshot")
def get_screenshot(request: Request, video_id: int) -> FileResponse:
    detail = _store(request).get_video(video_id)
    path = _data_file(request, detail["video"].get("screenshot"))
    return FileResponse(path)


@router.post("/videos/{video_id}/play")
def play_video(request: Request, video_id: int, body: PlayRequest) -> dict[str, Any]:
    store = _store(request)
    video_path, _ = store.get_video_path(video_id)
    key = path_key(video_path)
    roots = store.list_roots()
    if not any(is_within(key, root["path_key"]) for root in roots):
        raise PlaybackError("文件不在扫描目录内", code="path_outside_root")
    if not Path(video_path).is_file():
        raise PlaybackError("文件不存在", code="path_not_found")
    player = resolve_player(store.get_settings(), body.player)
    pid = launch(player, video_path, body.seek)
    return {"ok": True, "player": player["name"], "pid": pid}


@router.get("/players")
def list_players() -> dict[str, Any]:
    return {"players": players_payload()}


def _data_file(request: Request, relative: str | None) -> Path:
    if not relative:
        raise NotFoundError("文件不存在")
    base = Path(request.app.state.data_dir).resolve()
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise NotFoundError("文件不存在") from exc
    if not candidate.is_file():
        raise NotFoundError("文件不存在")
    return candidate
