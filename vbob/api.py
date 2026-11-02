"""HTTP API 路由。

所有接口位于 ``/api`` 前缀下，错误由 ``app.py`` 的处理器统一封装为
``{"error": {"code", "message"}}``。扫描/刮削等耗时操作立即返回 202 和
``job_id``，进度与结果通过 ``/jobs/{job_id}`` 查询。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse

from . import __version__
from .errors import InvalidError, NotFoundError, PlaybackError
from .images import MAX_IMAGE_BYTES, download_image, save_cover
from .jobs import JobManager
from .paths import canonical_path, is_within, path_key
from .player import (
    launch,
    pick_executable,
    player_name_for_path,
    players_payload,
    resolve_player,
)
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
    DeleteScanRootRequest,
    DeleteVideoFilesRequest,
    FavoriteUpdate,
    MergeVideosRequest,
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
log = logging.getLogger(__name__)

SCRAPE_STATUSES = {"pending", "scraping", "success", "failed", "no_match", "skipped_manual"}


def _store(request: Request) -> Store:
    """取出 lifespan 注入的 Store 实例。"""
    return request.app.state.store


def _jobs(request: Request) -> JobManager:
    """取出 lifespan 注入的后台任务管理器。"""
    return request.app.state.jobs


@router.get("/health")
def health() -> dict[str, Any]:
    """健康检查，返回服务状态与版本号。"""
    return {"ok": True, "version": __version__}


# --------------------------------------------------------------------- settings


@router.get("/settings")
def get_settings(request: Request) -> dict[str, Any]:
    """读取完整设置（默认值叠加用户覆盖）。"""
    return _store(request).get_settings()


@router.put("/settings")
def update_settings(request: Request, patch: dict[str, Any]) -> dict[str, Any]:
    """深合并并校验局部设置。

    未知分组/字段或非法取值由 Store 抛出 InvalidError（422）。
    """
    return _store(request).update_settings(patch)


# -------------------------------------------------------------------- scan roots


@router.get("/scan-roots")
def list_roots(request: Request) -> dict[str, Any]:
    """列出全部扫描目录，含最近扫描状态与当前活动任务。"""
    return {"items": _store(request).list_roots()}


@router.post("/scan-roots", status_code=201)
def create_root(request: Request, body: ScanRootCreate) -> dict[str, Any]:
    """新增扫描目录并返回 201。

    错误：路径不存在或不是目录 422；路径重复或与已有目录嵌套 409。
    """
    return _store(request).create_root(
        body.path, body.enabled, body.scan_interval_minutes
    )


@router.put("/scan-roots/{root_id}")
def update_root(request: Request, root_id: int, body: ScanRootUpdate) -> dict[str, Any]:
    """局部更新扫描目录；未提供的字段保持不变。

    错误：目录不存在 404；无任何可更新字段或路径非法 422；
    修改后路径重复/重叠 409。
    """
    return _store(request).update_root(
        root_id,
        enabled=body.enabled,
        path=body.path,
        scan_interval_minutes=body.scan_interval_minutes,
    )


@router.delete("/scan-roots/{root_id}", status_code=204)
def delete_root(request: Request, root_id: int) -> Response:
    """删除扫描目录，成功返回 204；目录不存在返回 404。"""
    _store(request).delete_root(root_id)
    return Response(status_code=204)


@router.post("/scan-roots/{root_id}/delete")
def delete_root_with_options(
    request: Request, root_id: int, body: DeleteScanRootRequest
) -> dict[str, Any]:
    """删除目录并清理影片数据，可选同时删除磁盘文件。

    有排队/运行中的扫描或刮削任务时返回 409；文件删除失败不会中断
    数据清理，失败明细会随结果返回。演员资料始终保留。
    """
    return _store(request).delete_root_with_options(
        root_id, delete_files=body.delete_files
    )


# ------------------------------------------------------------------------ scans


@router.post("/scans", status_code=202)
def create_scan(request: Request, body: ScanRequest) -> dict[str, Any]:
    """启动扫描任务，立即返回 202 与 ``job_id``。

    未指定 ``root_id`` 时扫描所有启用的目录。
    错误：指定目录不存在 404；没有可用目录 422。
    """
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
    """对指定扫描目录启动批量刮削，返回 202 与 ``job_id``。

    错误：目录不存在 404。
    """
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
    """查询刮削日志，可按视频过滤；``limit`` 限制在 1-500。"""
    return {"items": _store(request).list_scrape_logs(limit, video_id=video_id)}


@router.get("/scans/{job_id}")
def get_scan_job(request: Request, job_id: str) -> dict[str, Any]:
    """按任务 ID 查询扫描任务（与 ``/jobs/{job_id}`` 等价），不存在返回 404。"""
    return _store(request).get_job(job_id)


# ------------------------------------------------------------------------- jobs


@router.get("/jobs")
def list_jobs(
    request: Request,
    limit: int = Query(20, ge=1, le=200),
    root_id: int | None = None,
) -> dict[str, Any]:
    """列出最近任务，可按扫描目录过滤；``limit`` 限制在 1-200。"""
    return {"items": _store(request).list_jobs(limit, root_id=root_id)}


@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str) -> dict[str, Any]:
    """查询任务详情（状态、进度、消息）；不存在返回 404。"""
    return _store(request).get_job(job_id)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(request: Request, job_id: str) -> dict[str, Any]:
    """请求取消任务；已完成/失败/已取消的任务原样返回。

    错误：任务不存在 404。
    """
    return _jobs(request).cancel(job_id)


# ---------------------------------------------------------------------- sources


@router.get("/sources")
def list_sources(request: Request) -> dict[str, Any]:
    """列出全部刮削源（含内置源）。"""
    return {"items": _store(request).list_sources()}


@router.post("/sources/restore-defaults")
def restore_default_sources(request: Request) -> dict[str, Any]:
    """补齐被删除的默认源；同名的现有源不会被覆盖。"""
    return {"items": _store(request).restore_default_sources()}


@router.post("/sources", status_code=201)
def create_source(request: Request, config: dict[str, Any]) -> dict[str, Any]:
    """新建刮削源并返回 201。

    配置由 ``source_config`` 校验：格式非法 422，名称重复 409。
    """
    return _store(request).create_source(config)


@router.put("/sources/{source_id}")
def update_source(request: Request, source_id: int, config: dict[str, Any]) -> dict[str, Any]:
    """整体更新刮削源配置。

    错误：源不存在 404；配置非法 422；内置源不可编辑或名称重复 409。
    """
    return _store(request).update_source(source_id, config)


@router.patch("/sources/{source_id}")
def update_source_state(
    request: Request, source_id: int, body: SourceStateUpdate
) -> dict[str, Any]:
    """仅调整启用状态与优先级（内置源也可用此接口）。

    错误：源不存在 404；未提供任何字段或取值非法 422。
    """
    return _store(request).update_source_state(
        source_id, enabled=body.enabled, priority=body.priority
    )


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(request: Request, source_id: int) -> Response:
    """删除刮削源，成功返回 204。

    错误：源不存在 404；内置源不可删除 409。
    """
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
    series: str | None = None,
    censored: str | None = None,
    scraped: bool | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """分页查询视频列表，返回 ``items``/``total``/``page``/``page_size``。

    除分页外支持关键字、编号、刮削状态、完整度、收藏、演员、标签、系列等过滤；
    ``sort=random`` 时用 ``seed`` 生成稳定的随机顺序，保证翻页一致。
    错误：排序方式、刮削状态或影片类型取值非法时返回 422。
    """
    # 这些是查询字符串，Pydantic 无法约束枚举，需在进入 Store 前手工校验。
    if sort not in SORT_ORDERS and sort != "random":
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
        series=series,
        censored=censored,
        scraped=scraped,
        seed=seed,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/videos/{video_id}")
def get_video(request: Request, video_id: int) -> dict[str, Any]:
    """获取视频详情：``video``、``metadata`` 与关联演员；不存在返回 404。"""
    return _store(request).get_video(video_id)


@router.patch("/videos/{video_id}/metadata")
def update_video_metadata(
    request: Request, video_id: int, body: VideoMetadataUpdate
) -> dict[str, Any]:
    """局部更新视频元数据，使用 ``version`` 做乐观锁。

    错误：视频不存在 404；版本不一致 409（code ``version_conflict``）；
    未知字段或取值非法 422。
    """
    fields = body.model_dump(exclude_unset=True)
    version = int(fields.pop("version"))
    # version 只用于冲突检测，不写入元数据；演员引用统一转成普通 dict。
    if "actresses" in fields and fields["actresses"] is not None:
        fields["actresses"] = [
            ref if isinstance(ref, dict) else ref.model_dump() for ref in fields["actresses"]
        ]
    return _store(request).update_video_metadata(video_id, fields, version)


@router.patch("/videos/{video_id}/favorite")
def set_video_favorite(
    request: Request, video_id: int, body: FavoriteUpdate
) -> dict[str, Any]:
    """单独切换视频收藏状态（不参与元数据乐观锁）；不存在返回 404。"""
    return _store(request).set_video_favorite(video_id, body.favorite)


@router.post("/videos/{video_id}/scrape", status_code=202)
def scrape_video(
    request: Request, video_id: int, body: ScrapeRequest
) -> dict[str, Any]:
    """启动单视频刮削任务，返回 202 与 ``job_id``；视频不存在返回 404。"""
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
    """查询单个视频的刮削日志；视频不存在返回 404。"""
    _store(request).get_video(video_id)
    return {"items": _store(request).list_scrape_logs(limit, video_id=video_id)}


@router.delete("/videos/{video_id}", status_code=204)
def delete_video(request: Request, video_id: int) -> Response:
    """删除视频记录（不删除磁盘文件），成功返回 204；不存在返回 404。"""
    _store(request).delete_video(video_id)
    return Response(status_code=204)


@router.post("/videos/{video_id}/merge")
def merge_videos(
    request: Request, video_id: int, body: MergeVideosRequest
) -> dict[str, Any]:
    """把源视频手动合并到目标视频，返回合并后的目标详情。

    文件、演员关联、日志和收藏都会转入目标；源记录删除。用于手动归并剧集。
    """
    return _store(request).merge_videos(video_id, body.source_ids)


@router.post("/videos/{video_id}/delete-files")
def delete_video_files(
    request: Request, video_id: int, body: DeleteVideoFilesRequest
) -> dict[str, Any]:
    """彻底删除选中的文件，并同步清理记录。

    只允许删除扫描目录内的文件；删除部分文件时影片记录保留，
    全部删除后影片记录一并移除。返回成功数、失败明细和剩余文件数。
    """
    return _store(request).delete_video_files(video_id, body.file_ids)


@router.get("/videos/{video_id}/cover")
def get_cover(request: Request, video_id: int) -> FileResponse:
    """返回视频封面文件；视频或封面不存在返回 404。"""
    detail = _store(request).get_video(video_id)
    metadata = detail["metadata"] or {}
    path = _data_file(request, metadata.get("cover_local"))
    return FileResponse(path)


@router.post("/videos/{video_id}/cover")
def upload_video_cover(
    request: Request, video_id: int, file: UploadFile = File(...)
) -> dict[str, Any]:
    """上传视频封面（jpeg/png/webp，上限 10MB）。

    多读 1 字节即可判断是否超限，无需信任请求头里的 Content-Length。
    图片格式由 ``save_cover`` 按文件签名识别。
    错误：视频不存在 404；文件过大或格式不支持 422。
    """
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
    """下载远程图片作为视频封面，同时记录原始 URL。

    错误：视频不存在 404；URL 非 http(s)、下载失败、过大或格式不支持 422。
    """
    store = _store(request)
    store.get_video(video_id)
    data = download_image(body.url)
    relative = save_cover(Path(request.app.state.data_dir), "videos", video_id, data)
    return store.update_video_cover(video_id, relative, body.url)


@router.get("/videos/{video_id}/screenshot")
def get_screenshot(request: Request, video_id: int) -> FileResponse:
    """返回视频截图文件；视频或截图不存在返回 404。"""
    detail = _store(request).get_video(video_id)
    path = _data_file(request, detail["video"].get("screenshot"))
    return FileResponse(path)


@router.post("/videos/{video_id}/play")
def play_video(request: Request, video_id: int, body: PlayRequest) -> dict[str, Any]:
    """用本机播放器打开视频，返回播放器名称与进程 PID。

    仅允许播放扫描目录内的文件，避免把任意路径交给播放器。
    错误：视频不存在 404；文件缺失（``path_not_found``）、文件越过扫描目录
    （``path_outside_root``）或播放器不可用（``player_not_found``/``no_player``）
    均返回 409。
    """
    store = _store(request)
    video_path, _ = store.get_video_path(video_id, body.file_id)
    key = path_key(video_path)
    roots = store.list_roots()
    if not any(is_within(key, root["path_key"]) for root in roots):
        raise PlaybackError("文件不在扫描目录内", code="path_outside_root")
    if not Path(video_path).is_file():
        # 网络共享未挂载/凭据失效时也会走到这里，日志保留完整路径便于排查。
        log.warning("playback file not accessible: %s", video_path)
        raise PlaybackError(
            f"文件不存在或当前无法访问：{video_path}", code="path_not_found"
        )
    player = resolve_player(store.get_settings(), body.player)
    pid = launch(player, video_path, body.seek)
    return {"ok": True, "player": player["name"], "pid": pid}


@router.get("/players")
def list_players() -> dict[str, Any]:
    """列出本机探测到的可用播放器。"""
    return {"players": players_payload()}


@router.post("/players/pick")
def pick_player_executable() -> dict[str, Any]:
    """弹出本机文件选择框，返回用户选择的播放器可执行文件。

    由后端弹框是因为浏览器无法获取本地文件的真实路径；用户取消时
    ``path`` 为 null。该接口只应在桌面环境下调用。
    """
    selected = pick_executable()
    if not selected:
        return {"path": None, "name": None}
    resolved = canonical_path(selected)
    if not Path(resolved).is_file():
        raise InvalidError("选择的文件不存在")
    return {"path": resolved, "name": player_name_for_path(resolved)}


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
    """分页查询演员列表；排序方式非法时返回 422。"""
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
    """新建演员并返回 201；姓名为空 422，同名已存在 409。"""
    result = _store(request).create_actress(body.name)
    return result["actress"]


@router.get("/actresses/{actress_id}")
def get_actress(request: Request, actress_id: int) -> dict[str, Any]:
    """获取演员详情；不存在返回 404。"""
    return _store(request).get_actress(actress_id)


@router.patch("/actresses/{actress_id}")
def update_actress(
    request: Request, actress_id: int, body: ActressUpdate
) -> dict[str, Any]:
    """局部更新演员资料，使用 ``version`` 做乐观锁。

    错误：演员不存在 404；版本不一致或姓名重复 409；字段非法 422。
    """
    fields = body.model_dump(exclude_unset=True)
    # version 仅用于冲突检测，不进入可更新字段。
    version = int(fields.pop("version"))
    result = _store(request).update_actress(actress_id, fields, version)
    return result["actress"]


@router.delete("/actresses/{actress_id}", status_code=204)
def delete_actress(request: Request, actress_id: int) -> Response:
    """删除演员，成功返回 204。

    错误：演员不存在 404；仍有关联视频 409。
    """
    _store(request).delete_actress(actress_id)
    return Response(status_code=204)


@router.patch("/actresses/{actress_id}/favorite")
def set_actress_favorite(
    request: Request, actress_id: int, body: FavoriteUpdate
) -> dict[str, Any]:
    """单独切换演员收藏状态；不存在返回 404。"""
    result = _store(request).set_actress_favorite(actress_id, body.favorite)
    return result["actress"]


@router.post("/actresses/{actress_id}/scrape", status_code=202)
def scrape_actress(
    request: Request, actress_id: int, body: ScrapeRequest
) -> dict[str, Any]:
    """启动演员资料刮削任务，返回 202 与 ``job_id``；演员不存在返回 404。"""
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
    """返回演员封面文件；演员或封面不存在返回 404。"""
    detail = _store(request).get_actress(actress_id)
    path = _data_file(request, detail["actress"].get("cover_local"))
    return FileResponse(path)


@router.post("/actresses/{actress_id}/cover")
def upload_actress_cover(
    request: Request, actress_id: int, file: UploadFile = File(...)
) -> dict[str, Any]:
    """上传演员封面（jpeg/png/webp，上限 10MB）。

    错误：演员不存在 404；文件过大或格式不支持 422。
    """
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
    """下载远程图片作为演员封面，同时记录原始 URL。

    错误：演员不存在 404；URL 非法、下载失败、过大或格式不支持 422。
    """
    store = _store(request)
    store.get_actress(actress_id)
    data = download_image(body.url)
    relative = save_cover(Path(request.app.state.data_dir), "actresses", actress_id, data)
    result = store.update_actress_cover(actress_id, relative, body.url)
    return result["actress"]


def _data_file(request: Request, relative: str | None) -> Path:
    """把数据库中的相对路径安全地解析为数据目录内的文件。

    ``resolve()`` 后再用 ``relative_to`` 校验，防止 ``..`` 或符号链接逃逸
    到数据目录之外；缺失、越界或非文件统一返回 404，避免泄露文件系统信息。
    """
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
