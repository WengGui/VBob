"""API 请求体模型。

Pydantic 只负责请求结构和基础范围校验；重名、版本冲突等业务规则由 Store 处理。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ScanRootCreate(BaseModel):
    """新建扫描目录。"""

    path: str = Field(min_length=1)
    enabled: bool = True
    scan_interval_minutes: int = Field(default=0, ge=0, le=10080)


class ScanRootUpdate(BaseModel):
    """更新扫描目录；为 None 的字段表示保持原值。"""

    enabled: bool | None = None
    path: str | None = None
    scan_interval_minutes: int | None = Field(default=None, ge=0, le=10080)


class ScanRequest(BaseModel):
    """触发扫描；root_id 为空时扫描所有启用目录，full 为真时忽略缓存重算特征。"""

    root_id: int | None = None
    full: bool = False


class PlayRequest(BaseModel):
    """播放请求；file_id 选择分组内的具体文件，seek 表示起播位置（秒）。"""

    player: str | None = None
    seek: float | None = Field(default=None, ge=0)
    file_id: int | None = None


class DeleteVideoFilesRequest(BaseModel):
    """彻底删除时选中的文件 ID 列表。"""

    file_ids: list[int] = Field(min_length=1)


class MergeVideosRequest(BaseModel):
    """手动合并视频时，被合并到目标视频的源视频 ID。"""

    source_ids: list[int] = Field(min_length=1)


class DetachVideoFilesRequest(BaseModel):
    """要移出剧集、拆分为独立视频的文件 ID。"""

    file_ids: list[int] = Field(min_length=1)


class DeleteScanRootRequest(BaseModel):
    """删除扫描目录；delete_files=True 时同时删除已收录的磁盘文件。"""

    delete_files: bool = False


class ScrapeRequest(BaseModel):
    """单个视频或演员的刮削选项。"""

    force: bool = False
    overwrite_manual: bool = False


class BatchScrapeRequest(ScrapeRequest):
    """按扫描目录批量刮削。"""

    root_id: int


class SourceStateUpdate(BaseModel):
    """只调整刮削源的启用状态或优先级。"""

    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=100000)


class ActressRef(BaseModel):
    """演员引用：已有演员给 id，新演员给 name。"""

    id: int | None = None
    name: str | None = None


class VideoMetadataUpdate(BaseModel):
    """手动编辑视频元数据；version 用于乐观锁校验。"""

    version: int = Field(ge=0)
    title: str | None = None
    original_title: str | None = None
    overview: str | None = None
    release_date: str | None = None
    year: int | None = Field(default=None, ge=0)
    runtime_sec: int | None = Field(default=None, ge=0)
    genres: list[str] | None = None
    tags: list[str] | None = None
    code: str | None = None
    studio: str | None = None
    series: str | None = None
    director: str | None = None
    censored: Literal["censored", "uncensored", "unknown"] | None = None
    country: str | None = None
    actresses: list[ActressRef] | None = None


class ActressCreate(BaseModel):
    """新建演员。"""

    name: str = Field(min_length=1)


class ActressUpdate(BaseModel):
    """手动编辑演员资料；version 用于乐观锁校验。"""

    version: int = Field(ge=0)
    name: str | None = None
    aliases: list[str] | None = None
    birth_date: str | None = None
    nationality: str | None = None
    height_cm: int | None = Field(default=None, ge=0)
    bust_cm: int | None = Field(default=None, ge=0)
    waist_cm: int | None = Field(default=None, ge=0)
    hips_cm: int | None = Field(default=None, ge=0)
    cup: str | None = None
    profile_url: str | None = None


class FavoriteUpdate(BaseModel):
    """切换收藏状态。"""

    favorite: bool


class CoverUrlUpdate(BaseModel):
    """通过图片 URL 更新封面。"""

    url: str = Field(min_length=1)
