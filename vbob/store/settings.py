"""设置读写。"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Iterable

from ..categories import CATEGORY_VALUES, DEFAULT_CATEGORY, normalize_category
from ..config import DEFAULT_SETTINGS, deep_merge
from ..db import Database, utc_now
from ..default_sources import DEFAULT_SOURCES
from ..errors import ConflictError, InvalidError, NotFoundError
from ..extractors import FeaturePipeline, FileRef
from ..names import actress_name_key
from ..paths import canonical_path, is_within, path_key
from ..source_config import validate_source_config
from .helpers import (
    SETTINGS_SECTIONS,
    SORT_ORDERS,
    _is_blank_value,
    _json_load,
    _metadata_dict,
    _row_dict,
    _validate_interval,
    _validate_settings_patch,
    remove_local_images,
    validate_settings,
)

log = logging.getLogger(__name__)


class SettingsMixin:
    """设置读写。"""

    def get_settings(self) -> dict[str, Any]:
        """读取设置，并用默认值补齐数据库中缺失的分组和字段。"""
        with self.db.connection() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        stored: dict[str, Any] = {}
        for row in rows:
            try:
                stored[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                # 单条设置损坏时忽略它，继续使用默认值，避免整个设置页无法打开。
                continue
        return deep_merge(DEFAULT_SETTINGS, stored)

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        """合并局部设置、整体校验后按分组写回。"""
        _validate_settings_patch(patch)
        merged = deep_merge(self.get_settings(), patch)
        merged = validate_settings(merged)
        now = utc_now()
        with self.db.transaction() as conn:
            # 校验后的完整分组逐组写入，读取时仍可按分组返回。
            for section in SETTINGS_SECTIONS:
                conn.execute(
                    "INSERT INTO settings(key, value, updated_at) VALUES(?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (section, json.dumps(merged[section]), now),
                )
        return merged

    # --------------------------------------------------------------- scan roots

    # 目录统计只计算仍存在的文件；scraped_count 以 metadata.is_complete 为准。
    ROOT_SELECT = """
        SELECT r.*,
               (SELECT COUNT(*) FROM videos v WHERE v.root_id=r.id AND v.present=1)
                   AS scanned_count,
               (SELECT COUNT(*) FROM video_files f JOIN videos v ON v.id=f.video_id
                WHERE v.root_id=r.id AND f.present=1)
                   AS file_count,
               (SELECT COUNT(*) FROM videos v JOIN metadata m ON m.video_id=v.id
                WHERE v.root_id=r.id AND v.present=1 AND m.is_complete=1)
                   AS scraped_count
        FROM scan_roots r
    """
