"""后台任务记录。"""

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


class JobMixin:
    """后台任务记录。"""

    def create_job(
        self,
        job_id: str,
        job_type: str,
        payload: dict[str, Any],
        root_id: int | None = None,
    ) -> None:
        """创建排队中的任务记录。"""
        with self.db.connection() as conn:
            conn.execute(
                "INSERT INTO jobs(id, type, status, payload, root_id, created_at) "
                "VALUES(?, ?, 'queued', ?, ?, ?)",
                (job_id, job_type, json.dumps(payload, ensure_ascii=False), root_id, utc_now()),
            )

    def update_job(self, job_id: str, **fields: Any) -> None:
        """更新任务的可变字段；未知字段会被忽略。"""
        allowed = {"status", "total", "done", "failed", "message", "started_at", "finished_at"}
        # 只接受白名单字段，确保动态拼接的 SET 子句安全。
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        assignments = ", ".join(f"{key}=?" for key in updates)
        with self.db.connection() as conn:
            conn.execute(
                f"UPDATE jobs SET {assignments} WHERE id=?",
                [*updates.values(), job_id],
            )

    def get_job(self, job_id: str) -> dict[str, Any]:
        """获取任务详情，并展开 JSON payload。"""
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise NotFoundError("任务不存在")
        data = _row_dict(row)
        data["payload"] = _json_load(data.get("payload"), {})
        data["cancel_requested"] = bool(data["cancel_requested"])
        return data

    def list_jobs(self, limit: int = 20, root_id: int | None = None) -> list[dict[str, Any]]:
        """按创建时间倒序列出任务，可按扫描目录过滤。"""
        with self.db.connection() as conn:
            if root_id is None:
                rows = conn.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE root_id=? ORDER BY created_at DESC LIMIT ?",
                    (root_id, limit),
                ).fetchall()
        result = []
        for row in rows:
            data = _row_dict(row)
            data["payload"] = _json_load(data.get("payload"), {})
            data["cancel_requested"] = bool(data["cancel_requested"])
            result.append(data)
        return result

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        """写入取消标记；已结束的任务保持不变。"""
        job = self.get_job(job_id)
        if job["status"] in {"succeeded", "failed", "canceled"}:
            return job
        with self.db.connection() as conn:
            conn.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (job_id,))
        return self.get_job(job_id)

    def cancel_queued_job(self, job_id: str) -> None:
        """直接把仍在排队的任务置为已取消。"""
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE jobs SET status='canceled', finished_at=?, message=? "
                "WHERE id=? AND status='queued'",
                (utc_now(), "任务已取消", job_id),
            )

    def recover_orphan_jobs(self) -> int:
        """服务启动时清理上个进程遗留的未结束任务，返回处理数量。"""
        with self.db.connection() as conn:
            cur = conn.execute(
                "UPDATE jobs SET status='failed', finished_at=?, message=? "
                "WHERE status IN ('queued', 'running')",
                (utc_now(), "服务重启，任务中断"),
            )
            return cur.rowcount
