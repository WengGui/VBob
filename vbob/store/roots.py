"""扫描目录与目录统计。"""

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


class RootMixin:
    """扫描目录与目录统计。"""

    def list_roots(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        """列出扫描目录，并附带每个目录当前活跃任务的摘要。"""
        sql = self.ROOT_SELECT
        if enabled_only:
            sql += " WHERE r.enabled=1"
        sql += " ORDER BY r.id ASC"
        with self.db.connection() as conn:
            rows = conn.execute(sql).fetchall()
            active = self._active_jobs(conn, [int(row["id"]) for row in rows])
        result = []
        for row in rows:
            data = self._root_dict(row)
            data["active_job"] = active.get(int(row["id"]))
            result.append(data)
        return result

    def get_root(self, root_id: int) -> dict[str, Any]:
        """按 ID 获取扫描目录，不存在时抛出 NotFoundError。"""
        with self.db.connection() as conn:
            row = conn.execute(
                self.ROOT_SELECT + " WHERE r.id=?", (root_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("扫描目录不存在")
            active = self._active_jobs(conn, [root_id])
        data = self._root_dict(row)
        data["active_job"] = active.get(root_id)
        return data

    def create_root(
        self,
        path: str,
        enabled: bool = True,
        scan_interval_minutes: int = 0,
        category: str = DEFAULT_CATEGORY,
        source_ids: Iterable[int] | None = None,
    ) -> dict[str, Any]:
        """新增扫描目录，拒绝重复目录以及与已有目录的父子重叠。"""
        resolved = canonical_path(path)
        key = path_key(resolved)
        if not Path(resolved).is_dir():
            raise InvalidError(f"目录不存在或不是目录: {resolved}")
        _validate_interval(scan_interval_minutes)
        category = normalize_category(category)
        with self.db.connection() as conn:
            existing = conn.execute("SELECT id, path, path_key FROM scan_roots").fetchall()
            selected = self._validate_source_ids(conn, source_ids or [])
        for row in existing:
            if row["path_key"] == key:
                raise ConflictError(f"扫描目录已存在: {row['path']}")
            # 双向判断重叠，既禁止新目录包含旧目录，也禁止新目录位于旧目录内部。
            if is_within(key, row["path_key"]) or is_within(row["path_key"], key):
                raise ConflictError(f"扫描目录与已有目录重叠: {row['path']}")
        now = utc_now()
        with self.db.connection() as conn:
            cur = conn.execute(
                "INSERT INTO scan_roots(path, path_key, enabled, scan_interval_minutes, "
                "category, source_ids, last_scan_status, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, 'idle', ?)",
                (
                    resolved,
                    key,
                    int(enabled),
                    scan_interval_minutes,
                    category,
                    json.dumps(selected),
                    now,
                ),
            )
        return self.get_root(int(cur.lastrowid))

    @staticmethod
    def _validate_source_ids(conn: Any, source_ids: Iterable[int]) -> list[int]:
        """校验目录限定的源 ID：去重并保持顺序，同时确认源存在。"""
        ids: list[int] = []
        for item in source_ids:
            if isinstance(item, bool) or not isinstance(item, int):
                raise InvalidError("source_ids 必须是刮削源 ID 数组")
            if item not in ids:
                ids.append(item)
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT id FROM sources WHERE id IN ({placeholders})", ids
        ).fetchall()
        found = {int(row["id"]) for row in rows}
        missing = [str(item) for item in ids if item not in found]
        if missing:
            raise InvalidError(f"刮削源不存在: {', '.join(missing)}")
        return ids

    def update_root(
        self,
        root_id: int,
        *,
        enabled: bool | None = None,
        path: str | None = None,
        scan_interval_minutes: int | None = None,
        category: str | None = None,
        source_ids: Iterable[int] | None = None,
    ) -> dict[str, Any]:
        """更新目录的启用状态、路径、扫描间隔、分类或限定源。

        修改路径时会把该目录下已有视频的相对位置映射到新根目录，
        元数据仍通过 video_id 关联，因此无需搬迁。
        """
        root = self.get_root(root_id)
        if (
            enabled is None
            and path is None
            and scan_interval_minutes is None
            and category is None
            and source_ids is None
        ):
            raise InvalidError("至少需要提供一个要修改的目录设置")
        if scan_interval_minutes is not None:
            _validate_interval(scan_interval_minutes)
        if category is not None:
            category = normalize_category(category)
        with self.db.transaction() as conn:
            selected = (
                self._validate_source_ids(conn, source_ids)
                if source_ids is not None
                else None
            )
            if path is not None:
                resolved = canonical_path(path)
                if not Path(resolved).is_dir():
                    raise InvalidError(f"目录不存在或不是目录: {resolved}")
                new_key = path_key(resolved)
                others = conn.execute(
                    "SELECT id, path, path_key FROM scan_roots WHERE id<>?", (root_id,)
                ).fetchall()
                for other in others:
                    if other["path_key"] == new_key:
                        raise ConflictError(f"扫描目录已存在: {other['path']}")
                    if is_within(new_key, other["path_key"]) or is_within(
                        other["path_key"], new_key
                    ):
                        raise ConflictError(f"扫描目录与已有目录重叠: {other['path']}")
                if new_key != root["path_key"]:
                    old_key = str(root["path_key"])
                    old_base = root["path"]
                    now = utc_now()
                    videos = conn.execute(
                        "SELECT id, path FROM videos WHERE root_id=?", (root_id,)
                    ).fetchall()
                    files = conn.execute(
                        """
                        SELECT f.id, f.video_id, f.path FROM video_files f
                        JOIN videos v ON v.id=f.video_id WHERE v.root_id=?
                        """,
                        (root_id,),
                    ).fetchall()
                    files_by_video: dict[int, list[Any]] = {}
                    for file in files:
                        files_by_video.setdefault(int(file["video_id"]), []).append(file)

                    if is_within(new_key, old_key):
                        # 新根是旧根的子目录：磁盘文件没有移动，不能再拼接相对路径。
                        # 仍在新根下的记录保持原路径；其余记录脱离该目录并标记缺失。
                        for video in videos:
                            video_id = int(video["id"])
                            video_files = files_by_video.get(video_id, [])
                            paths = [str(item["path"]) for item in video_files] or [
                                str(video["path"])
                            ]
                            if not any(is_within(path_key(path), new_key) for path in paths):
                                conn.execute(
                                    "UPDATE videos SET root_id=NULL, present=0, "
                                    "missing_since=?, updated_at=? WHERE id=?",
                                    (now, now, video_id),
                                )
                                conn.execute(
                                    "UPDATE video_files SET present=0, missing_since=?, "
                                    "updated_at=? WHERE video_id=?",
                                    (now, now, video_id),
                                )
                                continue
                            changed = False
                            for item in video_files:
                                if not is_within(path_key(item["path"]), new_key):
                                    conn.execute(
                                        "UPDATE video_files SET present=0, missing_since=?, "
                                        "updated_at=? WHERE id=?",
                                        (now, now, int(item["id"])),
                                    )
                                    changed = True
                            if changed:
                                self._refresh_video_from_files(conn, video_id)
                    elif is_within(old_key, new_key):
                        # 新根是旧根的父目录：原路径仍在新根下，不需要迁移。
                        pass
                    else:
                        # 目录被改名/移动到无关路径：按相对路径整体迁移。
                        planned: list[tuple[int, str, str]] = []
                        for video in videos:
                            relative = os.path.relpath(video["path"], old_base)
                            if relative.startswith(".."):
                                continue
                            new_path = canonical_path(os.path.join(resolved, relative))
                            planned.append((int(video["id"]), new_path, path_key(new_path)))
                        planned_files: list[tuple[int, str, str]] = []
                        for file in files:
                            relative = os.path.relpath(file["path"], old_base)
                            if relative.startswith(".."):
                                continue
                            new_path = canonical_path(os.path.join(resolved, relative))
                            planned_files.append((int(file["id"]), new_path, path_key(new_path)))
                        # 先整体检查 path_key 冲突，再写入，避免事务中途留下部分更新。
                        for _, _, key in planned:
                            conflict = conn.execute(
                                "SELECT 1 FROM videos WHERE path_key=? AND root_id<>?",
                                (key, root_id),
                            ).fetchone()
                            if conflict:
                                raise ConflictError("修改目录后存在路径冲突，请先清理重复记录")
                        for _, _, key in planned_files:
                            conflict = conn.execute(
                                """
                                SELECT 1 FROM video_files f JOIN videos v ON v.id=f.video_id
                                WHERE f.path_key=? AND v.root_id<>?
                                """,
                                (key, root_id),
                            ).fetchone()
                            if conflict:
                                raise ConflictError("修改目录后存在路径冲突，请先清理重复记录")
                        for video_id, new_path, new_path_key in planned:
                            conn.execute(
                                "UPDATE videos SET path=?, path_key=?, updated_at=? WHERE id=?",
                                (new_path, new_path_key, now, video_id),
                            )
                        for file_id, new_path, new_path_key in planned_files:
                            conn.execute(
                                "UPDATE video_files SET path=?, path_key=?, updated_at=? WHERE id=?",
                                (new_path, new_path_key, now, file_id),
                            )
                    conn.execute(
                        "UPDATE scan_roots SET path=?, path_key=? WHERE id=?",
                        (resolved, new_key, root_id),
                    )
            updates: list[str] = []
            params: list[Any] = []
            # 只从固定字段中拼接 SET 子句，不接收外部列名。
            if enabled is not None:
                updates.append("enabled=?")
                params.append(int(enabled))
            if scan_interval_minutes is not None:
                updates.append("scan_interval_minutes=?")
                params.append(scan_interval_minutes)
            if category is not None:
                updates.append("category=?")
                params.append(category)
                # 分类变化时同步目录下的视频，但保留用户手动改过分类的记录。
                conn.execute(
                    "UPDATE videos SET category=?, updated_at=? "
                    "WHERE root_id=? AND category_manual=0",
                    (category, utc_now(), root_id),
                )
            if selected is not None:
                updates.append("source_ids=?")
                params.append(json.dumps(selected))
            if updates:
                params.append(root_id)
                conn.execute(f"UPDATE scan_roots SET {', '.join(updates)} WHERE id=?", params)
        return self.get_root(root_id)

    def delete_root_with_options(self, root_id: int, *, delete_files: bool) -> dict[str, Any]:
        """删除目录配置及其影片数据，可选地同时删除磁盘文件。

        ``delete_files=False`` 时只清理目录和影片记录，磁盘文件保留；
        为 True 时删除该目录下已收录的文件，失败项会返回给前端。
        只要有排队/运行中的任务就拒绝删除，避免扫描线程继续写入。
        """
        root = self.get_root(root_id)
        with self.db.connection() as conn:
            active = conn.execute(
                "SELECT 1 FROM jobs WHERE root_id=? AND status IN ('queued','running') LIMIT 1",
                (root_id,),
            ).fetchone()
            if active:
                raise ConflictError("该目录有正在运行的任务，请等待完成或取消后再删除")
            files = conn.execute(
                """
                SELECT f.id, f.path, f.filename FROM video_files f
                JOIN videos v ON v.id=f.video_id WHERE v.root_id=?
                """,
                (root_id,),
            ).fetchall()
            video_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM videos WHERE root_id=?", (root_id,)
                ).fetchone()["n"]
            )

        deleted_files = 0
        failed: list[dict[str, Any]] = []
        if delete_files:
            root_key = str(root["path_key"])
            for file in files:
                path = str(file["path"])
                if not is_within(path_key(path), root_key):
                    failed.append(
                        {
                            "filename": file["filename"],
                            "message": "文件不在该目录内，已跳过",
                        }
                    )
                    continue
                target = Path(path)
                if target.exists():
                    try:
                        target.unlink()
                    except OSError as exc:
                        failed.append(
                            {"filename": file["filename"], "message": f"删除失败: {exc}"}
                        )
                        continue
                deleted_files += 1

        with self.db.transaction() as conn:
            conn.execute(
                "DELETE FROM scrape_logs WHERE video_id IN (SELECT id FROM videos WHERE root_id=?)",
                (root_id,),
            )
            conn.execute("DELETE FROM videos WHERE root_id=?", (root_id,))
            conn.execute("DELETE FROM scan_roots WHERE id=?", (root_id,))
        return {
            "deleted_videos": video_count,
            "deleted_files": deleted_files,
            "failed_files": failed,
        }

    def delete_root(self, root_id: int) -> None:
        """删除扫描目录，但保留其视频与元数据历史并标记为缺失。"""
        self.get_root(root_id)
        now = utc_now()
        with self.db.transaction() as conn:
            # 先软标记缺失，再删目录；外键 ON DELETE SET NULL 会让视频脱离根目录但记录仍在。
            conn.execute(
                "UPDATE videos SET present=0, missing_since=?, updated_at=? WHERE root_id=?",
                (now, now, root_id),
            )
            conn.execute(
                """
                UPDATE video_files SET present=0, missing_since=?, updated_at=?
                WHERE video_id IN (SELECT id FROM videos WHERE root_id=?)
                """,
                (now, now, root_id),
            )
            conn.execute("DELETE FROM scan_roots WHERE id=?", (root_id,))

    def start_root_scan(self, root_id: int) -> None:
        """记录扫描开始，并清除上一次的结束信息。"""
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE scan_roots SET last_scan_status='running', last_scan_started_at=?, "
                "last_scan_finished_at=NULL, last_scan_duration_ms=NULL WHERE id=?",
                (utc_now(), root_id),
            )

    def finish_root_scan(self, root_id: int, status: str, duration_ms: int) -> None:
        """记录扫描结束状态、耗时和完成时间。"""
        now = utc_now()
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE scan_roots SET last_scan_status=?, last_scan_finished_at=?, "
                "last_scan_duration_ms=?, last_scan_at=?, last_scan_started_at=COALESCE("
                "last_scan_started_at, ?) WHERE id=?",
                (status, now, duration_ms, now, now, root_id),
            )

    def touch_root_scanned(self, root_id: int) -> None:
        """只刷新最近扫描时间，不改动状态字段。"""
        with self.db.connection() as conn:
            conn.execute("UPDATE scan_roots SET last_scan_at=? WHERE id=?", (utc_now(), root_id))

    @staticmethod
    def _active_jobs(conn: Any, root_ids: list[int]) -> dict[int, dict[str, Any]]:
        """查询这些目录下排队或运行中的任务，并按 root_id 建索引。"""
        if not root_ids:
            return {}
        placeholders = ",".join("?" for _ in root_ids)
        rows = conn.execute(
            f"SELECT id, type, status, done, total, message, root_id FROM jobs "
            f"WHERE root_id IN ({placeholders}) AND status IN ('queued','running')",
            root_ids,
        ).fetchall()
        return {
            int(row["root_id"]): {
                "id": row["id"],
                "type": row["type"],
                "status": row["status"],
                "done": row["done"],
                "total": row["total"],
                "message": row["message"],
            }
            for row in rows
            if row["root_id"] is not None
        }

    @staticmethod
    def _root_dict(row: Any) -> dict[str, Any]:
        """把目录行的 SQLite 整数值转换成 API 需要的布尔/整数类型。"""
        data = _row_dict(row)
        data["enabled"] = bool(data["enabled"])
        data["scan_interval_minutes"] = int(data.get("scan_interval_minutes") or 0)
        data["category"] = data.get("category") or DEFAULT_CATEGORY
        # source_ids 以 JSON 数组存储，空数组表示“该分类下全部启用源”。
        data["source_ids"] = [int(item) for item in _json_load(data.get("source_ids"), [])]
        return data

    # ------------------------------------------------------------------- sources
