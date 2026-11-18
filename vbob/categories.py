"""媒体类型枚举。

源、扫描目录和视频共用同一组取值；``other`` 同时作为未分类的兜底。
"""

from __future__ import annotations

from typing import Any

from .errors import InvalidError

CATEGORY_VALUES: tuple[str, ...] = ("movie", "anime", "series", "jav", "other")
CATEGORY_LABELS: dict[str, str] = {
    "movie": "电影",
    "anime": "动漫",
    "series": "剧集",
    "jav": "JAV",
    "other": "其他",
}
DEFAULT_CATEGORY = "other"


def normalize_category(value: Any, field: str = "category") -> str:
    """校验媒体类型取值；缺省时返回 other。"""
    if value is None:
        return DEFAULT_CATEGORY
    if not isinstance(value, str) or value not in CATEGORY_VALUES:
        allowed = " / ".join(CATEGORY_VALUES)
        raise InvalidError(f"{field} 必须是 {allowed} 之一")
    return value
