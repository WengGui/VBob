from __future__ import annotations

from pydantic import BaseModel, Field


class ScanRootCreate(BaseModel):
    path: str = Field(min_length=1)
    enabled: bool = True


class ScanRootUpdate(BaseModel):
    enabled: bool


class ScanRequest(BaseModel):
    root_id: int | None = None
    full: bool = False


class PlayRequest(BaseModel):
    player: str | None = None
    seek: float | None = Field(default=None, ge=0)
