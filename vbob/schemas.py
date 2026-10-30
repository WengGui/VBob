from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ScanRootCreate(BaseModel):
    path: str = Field(min_length=1)
    enabled: bool = True
    scan_interval_minutes: int = Field(default=0, ge=0, le=10080)


class ScanRootUpdate(BaseModel):
    enabled: bool | None = None
    path: str | None = None
    scan_interval_minutes: int | None = Field(default=None, ge=0, le=10080)


class ScanRequest(BaseModel):
    root_id: int | None = None
    full: bool = False


class PlayRequest(BaseModel):
    player: str | None = None
    seek: float | None = Field(default=None, ge=0)


class ScrapeRequest(BaseModel):
    force: bool = False
    overwrite_manual: bool = False


class BatchScrapeRequest(ScrapeRequest):
    root_id: int


class SourceStateUpdate(BaseModel):
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=100000)


class ActressRef(BaseModel):
    id: int | None = None
    name: str | None = None


class VideoMetadataUpdate(BaseModel):
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
    name: str = Field(min_length=1)


class ActressUpdate(BaseModel):
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
    favorite: bool


class CoverUrlUpdate(BaseModel):
    url: str = Field(min_length=1)
