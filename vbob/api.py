from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse

from . import __version__
from .errors import InvalidError, NotFoundError, PlaybackError
from .images import MAX_IMAGE_BYTES, download_image, save_cover
from .jobs import JobManager
from .paths import is_within, path_key
from .player import launch, players_payload, resolve_player
from .scans import start_scan
from .scrape_jobs import (
    start_actress_scrape,
    start_root_scrape,
    start_video_scrape,
)
from .schemas import (
    ActressCreate,
    ActressUpdate,
    BatchScrapeRequest,
    CoverUrlUpdate,
    FavoriteUpdate,
    PlayRequest,
    ScanRequest,
    ScanRootCreate,
    ScanRootUpdate,
    ScrapeRequest,
    SourceStateUpdate,
    VideoMetadataUpdate,
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
    return _store(request).create_root(
        body.path, body.enabled, body.scan_interval_minutes
    )


@router.put("/scan-roots/{root_id}")
def update_root(request: Request, root_id: int, body: ScanRootUpdate) -> dict[str, Any]:
    return _store(request).update_root(
        root_id,
        enabled=body.enabled,
        path=body.path,
        scan_interval_minutes=body.scan_interval_minutes,
    )


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

    job_id = start_scan(
        store,
        _jobs(request),
        root_ids,
        full=body.full,
        root_id=body.root_id,
    )
    return {"job_id": job_id}


@router.post("/scrapes", status_code=202)
def create_scrape(request: Request, body: BatchScrapeRequest) -> dict[str, Any]:
    job_id = start_root_scrape(
        _store(request),
        _jobs(request),
        request.app.state.data_dir,
        body.root_id,
        force=body.force,
        overwrite_manual=body.overwrite_manual,
    )
    return {"job_id": job_id}


@router.get("/scrape-logs")
def list_scrape_logs(
    request: Request,
    video_id: int | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    return {"items": _store(request).list_scrape_logs(limit, video_id=video_id)}


@router.get("/scans/{job_id}")
def get_scan_job(request: Request, job_id: str) -> dict[str, Any]:
    return _store(request).get_job(job_id)


# ------------------------------------------------------------------------- jobs


@router.get("/jobs")
def list_jobs(
    request: Request,
    limit: int = Query(20, ge=1, le=200),
    root_id: int | None = None,
) -> dict[str, Any]:
    return {"items": _store(request).list_jobs(limit, root_id=root_id)}


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
    present: bool = True,
    sort: str = "updated_at",
    complete: bool | None = None,
    favorite: bool | None = None,
    actress_id: int | None = None,
    tag: str | None = None,
    censored: str | None = None,
) -> dict[str, Any]:
    if sort not in SORT_ORDERS:
        raise InvalidError(f"不支持的排序方式: {sort}")
    if scrape_status is not None and scrape_status not in SCRAPE_STATUSES:
        raise InvalidError(f"不支持的刮削状态: {scrape_status}")
    if censored is not None and censored not in {"censored", "uncensored", "unknown"}:
        raise InvalidError("不支持的影片类型")
    items, total = _store(request).list_videos(
        page=page,
        page_size=page_size,
        q=q,
        has_code=has_code,
        scrape_status=scrape_status,
        present=present,
        sort=sort,
        complete=complete,
        favorite=favorite,
        actress_id=actress_id,
        tag=tag,
        censored=censored,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/videos/{video_id}")
def get_video(request: Request, video_id: int) -> dict[str, Any]:
    return _store(request).get_video(video_id)


@router.patch("/videos/{video_id}/metadata")
def update_video_metadata(
    request: Request, video_id: int, body: VideoMetadataUpdate
) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True)
    version = int(fields.pop("version"))
    if "actresses" in fields and fields["actresses"] is not None:
        fields["actresses"] = [
            ref if isinstance(ref, dict) else ref.model_dump() for ref in fields["actresses"]
        ]
    return _store(request).update_video_metadata(video_id, fields, version)


@router.patch("/videos/{video_id}/favorite")
def set_video_favorite(
    request: Request, video_id: int, body: FavoriteUpdate
) -> dict[str, Any]:
    return _store(request).set_video_favorite(video_id, body.favorite)


@router.post("/videos/{video_id}/scrape", status_code=202)
def scrape_video(
    request: Request, video_id: int, body: ScrapeRequest
) -> dict[str, Any]:
    store = _store(request)
    store.get_video(video_id)
    job_id = start_video_scrape(
        store,
        _jobs(request),
        request.app.state.data_dir,
        video_id,
        force=body.force,
        overwrite_manual=body.overwrite_manual,
    )
    return {"job_id": job_id}


@router.get("/videos/{video_id}/scrape-logs")
def video_scrape_logs(
    request: Request,
    video_id: int,
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    _store(request).get_video(video_id)
    return {"items": _store(request).list_scrape_logs(limit, video_id=video_id)}


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


@router.post("/videos/{video_id}/cover")
def upload_video_cover(
    request: Request, video_id: int, file: UploadFile = File(...)
) -> dict[str, Any]:
    store = _store(request)
    store.get_video(video_id)
    data = file.file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise InvalidError("封面文件过大（上限 10MB）")
    relative = save_cover(Path(request.app.state.data_dir), "videos", video_id, data)
    return store.update_video_cover(video_id, relative)


@router.put("/videos/{video_id}/cover")
def set_video_cover_url(
    request: Request, video_id: int, body: CoverUrlUpdate
) -> dict[str, Any]:
    store = _store(request)
    store.get_video(video_id)
    data = download_image(body.url)
    relative = save_cover(Path(request.app.state.data_dir), "videos", video_id, data)
    return store.update_video_cover(video_id, relative, body.url)


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


# --------------------------------------------------------------------- actresses

ACTRESS_SORTS = {"video_count", "name", "updated_at", "birth_date"}


@router.get("/actresses")
def list_actresses(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    q: str | None = None,
    complete: bool | None = None,
    favorite: bool | None = None,
    sort: str = "video_count",
) -> dict[str, Any]:
    if sort not in ACTRESS_SORTS:
        raise InvalidError(f"不支持的排序方式: {sort}")
    items, total = _store(request).list_actresses(
        page=page,
        page_size=page_size,
        q=q,
        complete=complete,
        favorite=favorite,
        sort=sort,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/actresses", status_code=201)
def create_actress(request: Request, body: ActressCreate) -> dict[str, Any]:
    result = _store(request).create_actress(body.name)
    return result["actress"]


@router.get("/actresses/{actress_id}")
def get_actress(request: Request, actress_id: int) -> dict[str, Any]:
    return _store(request).get_actress(actress_id)


@router.patch("/actresses/{actress_id}")
def update_actress(
    request: Request, actress_id: int, body: ActressUpdate
) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True)
    version = int(fields.pop("version"))
    result = _store(request).update_actress(actress_id, fields, version)
    return result["actress"]


@router.delete("/actresses/{actress_id}", status_code=204)
def delete_actress(request: Request, actress_id: int) -> Response:
    _store(request).delete_actress(actress_id)
    return Response(status_code=204)


@router.patch("/actresses/{actress_id}/favorite")
def set_actress_favorite(
    request: Request, actress_id: int, body: FavoriteUpdate
) -> dict[str, Any]:
    result = _store(request).set_actress_favorite(actress_id, body.favorite)
    return result["actress"]


@router.post("/actresses/{actress_id}/scrape", status_code=202)
def scrape_actress(
    request: Request, actress_id: int, body: ScrapeRequest
) -> dict[str, Any]:
    store = _store(request)
    store.get_actress(actress_id)
    job_id = start_actress_scrape(
        store,
        _jobs(request),
        request.app.state.data_dir,
        actress_id,
        force=body.force,
        overwrite_manual=body.overwrite_manual,
    )
    return {"job_id": job_id}


@router.get("/actresses/{actress_id}/cover")
def get_actress_cover(request: Request, actress_id: int) -> FileResponse:
    detail = _store(request).get_actress(actress_id)
    path = _data_file(request, detail["actress"].get("cover_local"))
    return FileResponse(path)


@router.post("/actresses/{actress_id}/cover")
def upload_actress_cover(
    request: Request, actress_id: int, file: UploadFile = File(...)
) -> dict[str, Any]:
    store = _store(request)
    store.get_actress(actress_id)
    data = file.file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise InvalidError("封面文件过大（上限 10MB）")
    relative = save_cover(Path(request.app.state.data_dir), "actresses", actress_id, data)
    result = store.update_actress_cover(actress_id, relative)
    return result["actress"]


@router.put("/actresses/{actress_id}/cover")
def set_actress_cover_url(
    request: Request, actress_id: int, body: CoverUrlUpdate
) -> dict[str, Any]:
    store = _store(request)
    store.get_actress(actress_id)
    data = download_image(body.url)
    relative = save_cover(Path(request.app.state.data_dir), "actresses", actress_id, data)
    result = store.update_actress_cover(actress_id, relative, body.url)
    return result["actress"]


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
