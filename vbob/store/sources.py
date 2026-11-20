"""刮削源 CRUD、探测结果与默认源。"""

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


class SourceMixin:
    """刮削源 CRUD、探测结果与默认源。"""

    def list_sources(self) -> list[dict[str, Any]]:
        """按优先级从高到低列出所有刮削源。"""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM sources ORDER BY priority ASC, name ASC"
            ).fetchall()
        return [self._source_dict(row) for row in rows]

    def get_source(self, source_id: int) -> dict[str, Any]:
        """按 ID 获取刮削源。"""
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        if row is None:
            raise NotFoundError("刮削源不存在")
        return self._source_dict(row)

    def create_source(self, config: dict[str, Any]) -> dict[str, Any]:
        """校验并新增自定义刮削源。"""
        normalized = validate_source_config(config)
        name = normalized["name"]
        with self.db.connection() as conn:
            if conn.execute("SELECT 1 FROM sources WHERE name=?", (name,)).fetchone():
                raise ConflictError(f"源名称已存在: {name}")
            now = utc_now()
            # 完整配置存 config_json；name/enabled/priority 另存列以支持唯一约束和排序。
            cur = conn.execute(
                "INSERT INTO sources(name, enabled, priority, category, version, "
                "config_json, builtin, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, 1, ?, 0, ?, ?)",
                (
                    name,
                    int(normalized["enabled"]),
                    normalized["priority"],
                    normalized["category"],
                    json.dumps(normalized, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            source_id = int(cur.lastrowid)
        return self.get_source(source_id)

    def update_source(self, source_id: int, config: dict[str, Any]) -> dict[str, Any]:
        """整体替换自定义刮削源的配置；内置源只允许调整状态。"""
        existing = self.get_source(source_id)
        if existing["builtin"]:
            raise ConflictError("内置源不可编辑，只能启用/禁用或调整优先级")
        normalized = validate_source_config(config)
        with self.db.connection() as conn:
            duplicate = conn.execute(
                "SELECT 1 FROM sources WHERE name=? AND id<>?",
                (normalized["name"], source_id),
            ).fetchone()
            if duplicate:
                raise ConflictError(f"源名称已存在: {normalized['name']}")
            conn.execute(
                "UPDATE sources SET name=?, enabled=?, priority=?, category=?, "
                "version=version+1, config_json=?, updated_at=? WHERE id=?",
                (
                    normalized["name"],
                    int(normalized["enabled"]),
                    normalized["priority"],
                    normalized["category"],
                    json.dumps(normalized, ensure_ascii=False),
                    utc_now(),
                    source_id,
                ),
            )
        return self.get_source(source_id)

    def delete_source(self, source_id: int) -> None:
        """删除自定义源；内置源保留。

        同时清理目录限定列表和视频记住的偏好源，避免留下无效引用。
        """
        source = self.get_source(source_id)
        if source["builtin"]:
            raise ConflictError("内置源不可删除，只能禁用")
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
            roots = conn.execute("SELECT id, source_ids FROM scan_roots").fetchall()
            for root in roots:
                selected = _json_load(root["source_ids"], [])
                if source_id in selected:
                    remaining = [item for item in selected if item != source_id]
                    conn.execute(
                        "UPDATE scan_roots SET source_ids=? WHERE id=?",
                        (json.dumps(remaining), int(root["id"])),
                    )
            conn.execute(
                "UPDATE metadata SET source_id=NULL WHERE source_id=?", (source_id,)
            )

    def update_source_state(
        self, source_id: int, *, enabled: bool | None = None, priority: int | None = None
    ) -> dict[str, Any]:
        """只更新源的启用状态或优先级，并同步 config_json 中的副本。"""
        source = self.get_source(source_id)
        if enabled is None and priority is None:
            raise InvalidError("至少需要提供 enabled 或 priority")
        if enabled is not None and not isinstance(enabled, bool):
            raise InvalidError("enabled 必须是布尔值")
        if priority is not None and (
            isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 100000
        ):
            raise InvalidError("priority 必须是 0-100000 的整数")
        config = dict(source["config"])
        if enabled is not None:
            config["enabled"] = enabled
            source["enabled"] = enabled
        if priority is not None:
            config["priority"] = priority
            source["priority"] = priority
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE sources SET enabled=?, priority=?, version=version+1, "
                "config_json=?, updated_at=? WHERE id=?",
                (
                    int(source["enabled"]),
                    source["priority"],
                    json.dumps(config, ensure_ascii=False),
                    utc_now(),
                    source_id,
                ),
            )
        return self.get_source(source_id)

    def save_source_probe(self, source_id: int, result: dict[str, Any]) -> dict[str, Any]:
        """记录一次连通性检测结果；不修改 updated_at，避免看起来像配置被改过。"""
        checked_at = str(result.get("checked_at") or utc_now())
        with self.db.connection() as conn:
            cur = conn.execute(
                "UPDATE sources SET last_test_at=?, last_test_result_json=? WHERE id=?",
                (checked_at, json.dumps(result, ensure_ascii=False), source_id),
            )
            if cur.rowcount == 0:
                raise NotFoundError("刮削源不存在")
        return self.get_source(source_id)

    @staticmethod
    def _source_dict(row: Any) -> dict[str, Any]:
        """展开源记录的 config_json，并转换布尔列。"""
        data = _row_dict(row)
        data["config"] = _json_load(data.pop("config_json", None), {})
        data["last_test_result"] = _json_load(
            data.pop("last_test_result_json", None), None
        )
        data["enabled"] = bool(data["enabled"])
        data["builtin"] = bool(data["builtin"])
        return data

    def seed_default_sources(self) -> int:
        """首次启动时写入预置刮削源，返回新增数量。

        通过 app_meta 标记保证只执行一次；用户删除默认源后不会被自动加回，
        需要在设置页手动点击“恢复默认源”。
        """
        with self.db.transaction() as conn:
            marker = conn.execute(
                "SELECT value FROM app_meta WHERE key='default_sources_seeded'"
            ).fetchone()
            if marker is not None:
                return 0
            inserted = self._insert_missing_default_sources(conn)
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES('default_sources_seeded', '1')"
            )
        return inserted

    def restore_default_sources(self) -> list[dict[str, Any]]:
        """补齐被删除的默认源；已存在的同名源保持原配置不变。"""
        with self.db.transaction() as conn:
            self._insert_missing_default_sources(conn)
        return self.list_sources()

    @staticmethod
    def _insert_missing_default_sources(conn: Any) -> int:
        """按名称插入缺失的默认源；默认源可编辑，因此 builtin=0。"""
        inserted = 0
        now = utc_now()
        for raw in DEFAULT_SOURCES:
            name = str(raw["name"])
            if conn.execute("SELECT 1 FROM sources WHERE name=?", (name,)).fetchone():
                continue
            config = validate_source_config(raw)
            conn.execute(
                "INSERT INTO sources(name, enabled, priority, category, version, "
                "config_json, builtin, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, 1, ?, 0, ?, ?)",
                (
                    config["name"],
                    int(config["enabled"]),
                    int(config["priority"]),
                    config["category"],
                    json.dumps(config, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            inserted += 1
        return inserted

    # -------------------------------------------------------------------- videos
