"""数据访问层。

Store 集中封装设置、扫描目录、刮削源、视频、演员和任务相关的 SQL；
同时负责 JSON 字段的序列化/反序列化、乐观锁版本检查，以及元数据和演员完整度的重算。
所有跨表写入尽量放在 ``Database.transaction()`` 中，保证状态一致。
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Iterable

from .config import DEFAULT_SETTINGS, deep_merge
from .db import Database, utc_now
from .default_sources import DEFAULT_SOURCES
from .extractors import FeaturePipeline, FileRef
from .errors import ConflictError, InvalidError, NotFoundError
from .names import actress_name_key
from .paths import canonical_path, is_within, path_key
from .source_config import validate_source_config

log = logging.getLogger(__name__)

# 允许写入 settings 表的三个分组，与 DEFAULT_SETTINGS 的顶层 key 对应。
SETTINGS_SECTIONS = {"scan", "scraping", "playback"}
# 排序片段白名单：避免把用户输入的 sort 直接拼进 SQL，同时在相同排序值后按 id 稳定排序。
SORT_ORDERS = {
    "updated_at": "v.updated_at DESC, v.id DESC",
    "filename": "v.filename COLLATE NOCASE ASC, v.id ASC",
    "year": "m.year DESC NULLS LAST, v.id DESC",
    "title": "m.title COLLATE NOCASE ASC NULLS LAST, v.id ASC",
    "code": "COALESCE(m.code, v.jav_code) COLLATE NOCASE ASC NULLS LAST, v.id ASC",
}


def _row_dict(row: Any) -> dict[str, Any]:
    """把 sqlite3.Row 转成普通 dict，便于后续 pop 和 JSON 处理。"""
    return dict(row)


def _json_load(value: str | None, fallback: Any) -> Any:
    """解析数据库中的 JSON 文本；空值或损坏数据回退到默认值。"""
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _is_blank_value(value: Any) -> bool:
    """判断字段是否为空，用于允许刮削补全“手动标记但没填内容”的字段。"""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip() or value.strip() in {"[]", "{}"}
    if isinstance(value, (list, dict)):
        return not value
    return False


class Store:
    """应用的全部数据库读写入口。"""

    def __init__(self, db: Database) -> None:
        """绑定数据库封装。"""
        self.db = db

    # ------------------------------------------------------------------ settings

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
        self, path: str, enabled: bool = True, scan_interval_minutes: int = 0
    ) -> dict[str, Any]:
        """新增扫描目录，拒绝重复目录以及与已有目录的父子重叠。"""
        resolved = canonical_path(path)
        key = path_key(resolved)
        if not Path(resolved).is_dir():
            raise InvalidError(f"目录不存在或不是目录: {resolved}")
        _validate_interval(scan_interval_minutes)
        with self.db.connection() as conn:
            existing = conn.execute("SELECT id, path, path_key FROM scan_roots").fetchall()
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
                "last_scan_status, created_at) VALUES(?, ?, ?, ?, 'idle', ?)",
                (resolved, key, int(enabled), scan_interval_minutes, now),
            )
        return self.get_root(int(cur.lastrowid))

    def update_root(
        self,
        root_id: int,
        *,
        enabled: bool | None = None,
        path: str | None = None,
        scan_interval_minutes: int | None = None,
    ) -> dict[str, Any]:
        """更新目录的启用状态、路径或自动扫描间隔。

        修改路径时会把该目录下已有视频的相对位置映射到新根目录，
        元数据仍通过 video_id 关联，因此无需搬迁。
        """
        root = self.get_root(root_id)
        if enabled is None and path is None and scan_interval_minutes is None:
            raise InvalidError("至少需要提供一个要修改的目录设置")
        if scan_interval_minutes is not None:
            _validate_interval(scan_interval_minutes)
        with self.db.transaction() as conn:
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
        return data

    # ------------------------------------------------------------------- sources

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
                "INSERT INTO sources(name, enabled, priority, version, config_json, "
                "builtin, created_at, updated_at) VALUES(?, ?, ?, 1, ?, 0, ?, ?)",
                (
                    name,
                    int(normalized["enabled"]),
                    normalized["priority"],
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
                "UPDATE sources SET name=?, enabled=?, priority=?, version=version+1, "
                "config_json=?, updated_at=? WHERE id=?",
                (
                    normalized["name"],
                    int(normalized["enabled"]),
                    normalized["priority"],
                    json.dumps(normalized, ensure_ascii=False),
                    utc_now(),
                    source_id,
                ),
            )
        return self.get_source(source_id)

    def delete_source(self, source_id: int) -> None:
        """删除自定义源；内置源保留。"""
        source = self.get_source(source_id)
        if source["builtin"]:
            raise ConflictError("内置源不可删除，只能禁用")
        with self.db.connection() as conn:
            conn.execute("DELETE FROM sources WHERE id=?", (source_id,))

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

    @staticmethod
    def _source_dict(row: Any) -> dict[str, Any]:
        """展开源记录的 config_json，并转换布尔列。"""
        data = _row_dict(row)
        data["config"] = _json_load(data.pop("config_json", None), {})
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
                "INSERT INTO sources(name, enabled, priority, version, config_json, "
                "builtin, created_at, updated_at) VALUES(?, ?, ?, 1, ?, 0, ?, ?)",
                (
                    config["name"],
                    int(config["enabled"]),
                    int(config["priority"]),
                    json.dumps(config, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            inserted += 1
        return inserted

    # -------------------------------------------------------------------- videos

    def load_scan_cache(self, root_id: int) -> dict[str, dict[str, Any]]:
        """按 path_key 建立目录内已有文件索引，供扫描时快速比对。

        返回的 ``id`` 是 video_files.id，``video_id`` 指向所属影片分组。
        """
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT f.id, f.video_id, f.path_key, f.size_bytes, f.mtime, f.present
                FROM video_files f JOIN videos v ON v.id = f.video_id
                WHERE v.root_id=?
                """,
                (root_id,),
            ).fetchall()
        return {row["path_key"]: dict(row) for row in rows}

    def merge_videos(self, target_id: int, source_ids: Iterable[int]) -> dict[str, Any]:
        """把多个视频手动合并为一个剧集分组。

        源视频的文件、刮削日志、演员关联和收藏都转移到目标视频，然后删除源记录。
        目标已有元数据时保留目标资料，只从源资料补全空字段；目标没有元数据时
        直接接收第一个源的完整元数据。文件路径不变，因此重扫仍会挂到目标分组。
        """
        sources = sorted({int(source_id) for source_id in source_ids if int(source_id) != target_id})
        if not sources:
            raise InvalidError("请选择要合并的其他视频")
        placeholders = ",".join("?" for _ in sources)
        with self.db.transaction() as conn:
            if conn.execute("SELECT 1 FROM videos WHERE id=?", (target_id,)).fetchone() is None:
                raise NotFoundError("目标视频不存在")
            existing = conn.execute(
                f"SELECT id FROM videos WHERE id IN ({placeholders})", sources
            ).fetchall()
            if len(existing) != len(sources):
                raise NotFoundError("部分要合并的视频不存在")
            target_meta = conn.execute(
                "SELECT * FROM metadata WHERE video_id=?", (target_id,)
            ).fetchone()
            for source_id in sources:
                source_meta = conn.execute(
                    "SELECT * FROM metadata WHERE video_id=?", (source_id,)
                ).fetchone()
                if target_meta is None and source_meta is not None:
                    # 目标还没有资料时，直接接管源元数据（包括封面和手动字段）。
                    conn.execute(
                        "UPDATE metadata SET video_id=? WHERE video_id=?",
                        (target_id, source_id),
                    )
                    target_meta = conn.execute(
                        "SELECT * FROM metadata WHERE video_id=?", (target_id,)
                    ).fetchone()
                elif target_meta is not None and source_meta is not None:
                    fields = (
                        "title", "original_title", "overview", "cover_url", "cover_local",
                        "year", "release_date", "runtime_sec", "genres", "tags", "code",
                        "studio", "series", "director", "censored", "country",
                    )
                    updates: dict[str, Any] = {}
                    for key in fields:
                        if _is_blank_value(target_meta[key]) and not _is_blank_value(
                            source_meta[key]
                        ):
                            updates[key] = source_meta[key]
                    if updates:
                        assignments = ", ".join(f"{key}=?" for key in updates)
                        conn.execute(
                            f"UPDATE metadata SET {assignments}, version=version+1, "
                            "updated_at=? WHERE video_id=?",
                            [*updates.values(), utc_now(), target_id],
                        )
                        target_meta = conn.execute(
                            "SELECT * FROM metadata WHERE video_id=?", (target_id,)
                        ).fetchone()
                conn.execute(
                    "UPDATE video_files SET video_id=? WHERE video_id=?",
                    (target_id, source_id),
                )
                conn.execute(
                    "UPDATE scrape_logs SET video_id=? WHERE video_id=?",
                    (target_id, source_id),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO video_actresses(video_id, actress_id, position)
                    SELECT ?, actress_id, position FROM video_actresses WHERE video_id=?
                    """,
                    (target_id, source_id),
                )
                favorite = conn.execute(
                    "SELECT favorite FROM videos WHERE id=?", (source_id,)
                ).fetchone()
                if favorite and favorite["favorite"]:
                    conn.execute("UPDATE videos SET favorite=1 WHERE id=?", (target_id,))
                conn.execute("DELETE FROM videos WHERE id=?", (source_id,))
            self._refresh_video_from_files(conn, target_id)
        return self.get_video(target_id)

    def backfill_episode_features(self) -> int:
        """为旧数据补充剧集识别特征，返回更新条数。

        早期版本没有 episode_key；只靠重新扫描无法更新未变化文件，因此在升级后
        执行一次：对既没有番号也没有剧集键的视频重新提取特征，再交给
        :meth:`merge_duplicate_videos` 合并同一剧集的多个文件。
        """
        with self.db.transaction() as conn:
            marker = conn.execute(
                "SELECT value FROM app_meta WHERE key='episode_features_backfilled_v2'"
            ).fetchone()
            if marker is not None:
                return 0
            rows = conn.execute(
                """
                SELECT v.id, v.path, v.filename, v.features, r.path AS root_path
                FROM videos v JOIN scan_roots r ON r.id=v.root_id
                WHERE json_extract(v.features, '$.jav_match_key') IS NULL
                  AND json_extract(v.features, '$.episode_key') IS NULL
                """
            ).fetchall()
            pipeline = FeaturePipeline()
            updated = 0
            now = utc_now()
            for row in rows:
                relative = os.path.relpath(str(row["path"]), str(row["root_path"]))
                if relative.startswith(".."):
                    continue
                parent = os.path.dirname(relative)
                dirs = tuple(reversed(parent.split(os.sep))) if parent else ()
                try:
                    detected = pipeline.extract(
                        FileRef(
                            filename=str(row["filename"]),
                            rel_path=relative,
                            dirs=dirs,
                        )
                    )
                except Exception:  # noqa: BLE001 - 单条失败不应影响启动
                    log.exception("backfill episode features failed for %s", row["filename"])
                    continue
                if not detected.get("episode_key"):
                    continue
                features = _json_load(row["features"], {})
                features.update(detected)
                conn.execute(
                    "UPDATE videos SET features=?, updated_at=? WHERE id=?",
                    (json.dumps(features, ensure_ascii=False), now, int(row["id"])),
                )
                updated += 1
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES('episode_features_backfilled_v2', '1')"
            )
        return updated

    def merge_duplicate_videos(self) -> int:
        """把同一目录下拥有相同番号的多条旧视频记录合并为一个分组。

        旧版本按“一行一个文件”保存，升级后会先把每个文件回填到 video_files；
        这里按 root_id +（番号或剧集键）找出重复分组，选择资料最完整的一行作为代表，
        迁移文件、元数据、演员关联和日志，然后删除多余行。重复执行是安全的。
        """
        merged = 0
        with self.db.transaction() as conn:
            # 兜底：为尚未建立文件记录的旧行补一条主文件记录。
            conn.execute(
                """
                INSERT INTO video_files(
                    video_id, path, path_key, filename, size_bytes, mtime,
                    duration_sec, present, missing_since, created_at, updated_at
                )
                SELECT v.id, v.path, v.path_key, v.filename, v.size_bytes, v.mtime,
                       v.duration_sec, v.present, v.missing_since, v.created_at, v.updated_at
                FROM videos v
                WHERE NOT EXISTS (SELECT 1 FROM video_files f WHERE f.video_id = v.id)
                """
            )
            rows = conn.execute(
                """
                SELECT v.id, v.root_id, v.present, v.favorite,
                       COALESCE(
                           json_extract(v.features, '$.jav_match_key'),
                           json_extract(v.features, '$.episode_key')
                       ) AS group_key,
                       (SELECT COUNT(*) FROM metadata m WHERE m.video_id=v.id) AS has_metadata,
                       COALESCE((SELECT m.is_complete FROM metadata m WHERE m.video_id=v.id), 0)
                           AS is_complete
                FROM videos v
                WHERE v.root_id IS NOT NULL
                  AND COALESCE(
                      json_extract(v.features, '$.jav_match_key'),
                      json_extract(v.features, '$.episode_key'),
                      ''
                  ) <> ''
                """
            ).fetchall()
            groups: dict[tuple[int, str], list[Any]] = {}
            for row in rows:
                groups.setdefault((int(row["root_id"]), str(row["group_key"])), []).append(row)

            for members in groups.values():
                if len(members) < 2:
                    continue
                # 优先保留资料完整、已刮削、文件仍存在的记录；同分时取最小 ID。
                representative = max(
                    members,
                    key=lambda row: (
                        bool(row["is_complete"]),
                        bool(row["has_metadata"]),
                        bool(row["present"]),
                        -int(row["id"]),
                    ),
                )
                keep_id = int(representative["id"])
                for member in members:
                    drop_id = int(member["id"])
                    if drop_id == keep_id:
                        continue
                    # 文件、日志、演员关联都转给代表行；元数据只在代表行没有时迁移。
                    conn.execute(
                        "UPDATE video_files SET video_id=? WHERE video_id=?", (keep_id, drop_id)
                    )
                    conn.execute(
                        "UPDATE scrape_logs SET video_id=? WHERE video_id=?", (keep_id, drop_id)
                    )
                    if not conn.execute(
                        "SELECT 1 FROM metadata WHERE video_id=?", (keep_id,)
                    ).fetchone():
                        conn.execute(
                            "UPDATE metadata SET video_id=? WHERE video_id=?",
                            (keep_id, drop_id),
                        )
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO video_actresses(video_id, actress_id, position)
                        SELECT ?, actress_id, position FROM video_actresses WHERE video_id=?
                        """,
                        (keep_id, drop_id),
                    )
                    if member["favorite"]:
                        conn.execute("UPDATE videos SET favorite=1 WHERE id=?", (keep_id,))
                    conn.execute("DELETE FROM videos WHERE id=?", (drop_id,))
                    merged += 1
                self._refresh_video_from_files(conn, keep_id)
        return merged

    @staticmethod
    def _refresh_video_from_files(conn: Any, video_id: int) -> None:
        """用 video_files 中的文件重算分组主文件与存在状态。

        优先选择仍存在的文件作为主文件（``videos.path/filename`` 等字段），
        所有文件都缺失时保留第一条路径并标记整个分组缺失。
        """
        files = conn.execute(
            """
            SELECT path, path_key, filename, size_bytes, mtime, duration_sec,
                   present, missing_since
            FROM video_files WHERE video_id=? ORDER BY present DESC, id ASC
            """,
            (video_id,),
        ).fetchall()
        now = utc_now()
        if not files:
            conn.execute(
                "UPDATE videos SET present=0, missing_since=?, updated_at=? WHERE id=?",
                (now, now, video_id),
            )
            return
        primary = files[0]
        present = 1 if any(row["present"] for row in files) else 0
        conn.execute(
            """
            UPDATE videos SET path=?, path_key=?, filename=?, size_bytes=?, mtime=?,
                   duration_sec=?, present=?, missing_since=?, updated_at=?
            WHERE id=?
            """,
            (
                primary["path"],
                primary["path_key"],
                primary["filename"],
                primary["size_bytes"],
                primary["mtime"],
                primary["duration_sec"],
                present,
                None if present else (primary["missing_since"] or now),
                now,
                video_id,
            ),
        )

    def upsert_video_file(
        self,
        *,
        root_id: int,
        path: str,
        key: str,
        filename: str,
        size: int,
        mtime: int,
        features: dict[str, Any],
        scan_status: str = "scanned",
    ) -> tuple[int, int, bool]:
        """新增或刷新一个视频文件，返回 ``(video_id, file_id, created)``。

        有番号的同一目录文件会挂到同一个 videos 分组下；没有番号的文件
        每个都是独立分组。已存在的文件复用原记录，从而保留元数据和收藏。
        """
        now = utc_now()
        features_json = json.dumps(features, ensure_ascii=False)
        with self.db.transaction() as conn:
            existing = conn.execute(
                "SELECT id, video_id FROM video_files WHERE path_key=?", (key,)
            ).fetchone()
            if existing is not None:
                video_id = int(existing["video_id"])
                conn.execute(
                    """
                    UPDATE video_files
                    SET path=?, filename=?, size_bytes=?, mtime=?, present=1,
                        missing_since=NULL, updated_at=?
                    WHERE id=?
                    """,
                    (path, filename, size, mtime, now, int(existing["id"])),
                )
                # 只有番号未变化时才整体刷新分组的特征，避免一个文件改名后
                # 把同组其他文件的分组键覆盖掉。
                current = conn.execute(
                    "SELECT features FROM videos WHERE id=?", (video_id,)
                ).fetchone()
                old_features = _json_load(current["features"], {})
                old_key = old_features.get("jav_match_key") or old_features.get("episode_key")
                new_key = features.get("jav_match_key") or features.get("episode_key")
                if not old_key or old_key == new_key:
                    conn.execute(
                        "UPDATE videos SET root_id=?, features=?, scan_status=?, updated_at=? "
                        "WHERE id=?",
                        (root_id, features_json, scan_status, now, video_id),
                    )
                else:
                    conn.execute(
                        "UPDATE videos SET root_id=?, scan_status=?, updated_at=? WHERE id=?",
                        (root_id, scan_status, now, video_id),
                    )
                self._refresh_video_from_files(conn, video_id)
                return video_id, int(existing["id"]), False

            group_key = features.get("jav_match_key") or features.get("episode_key")
            group = None
            if isinstance(group_key, str) and group_key:
                # 同一目录内相同番号或剧集键视为同一部影片的不同文件。
                group = conn.execute(
                    """
                    SELECT id FROM videos
                    WHERE root_id=? AND COALESCE(
                        json_extract(features, '$.jav_match_key'),
                        json_extract(features, '$.episode_key')
                    )=?
                    ORDER BY id ASC LIMIT 1
                    """,
                    (root_id, group_key),
                ).fetchone()
            if group is not None:
                video_id = int(group["id"])
                cur = conn.execute(
                    """
                    INSERT INTO video_files(
                        video_id, path, path_key, filename, size_bytes, mtime,
                        present, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (video_id, path, key, filename, size, mtime, now, now),
                )
                file_id = int(cur.lastrowid)
                conn.execute(
                    "UPDATE videos SET scan_status=?, updated_at=? WHERE id=?",
                    (scan_status, now, video_id),
                )
                self._refresh_video_from_files(conn, video_id)
                return video_id, file_id, True

            cur = conn.execute(
                """
                INSERT INTO videos(
                    root_id, path, path_key, filename, size_bytes, mtime, features,
                    present, scan_status, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (root_id, path, key, filename, size, mtime, features_json,
                 scan_status, now, now),
            )
            video_id = int(cur.lastrowid)
            cur = conn.execute(
                """
                INSERT INTO video_files(
                    video_id, path, path_key, filename, size_bytes, mtime,
                    present, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (video_id, path, key, filename, size, mtime, now, now),
            )
            return video_id, int(cur.lastrowid), True

    def mark_seen(self, file_id: int) -> None:
        """把之前缺失、本次重新扫描到的文件恢复为存在状态。"""
        now = utc_now()
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT video_id FROM video_files WHERE id=?", (file_id,)
            ).fetchone()
            if row is None:
                return
            conn.execute(
                "UPDATE video_files SET present=1, missing_since=NULL, updated_at=? WHERE id=?",
                (now, file_id),
            )
            self._refresh_video_from_files(conn, int(row["video_id"]))

    def mark_missing(self, root_id: int, seen_ids: Iterable[int]) -> int:
        """将本轮未出现的文件标记为缺失，返回受影响的文件数。

        文件标记完成后会重算所属分组：组内还有其他文件时整体仍为存在，
        全部缺失时分组的 videos.present 才会变成 0。
        """
        now = utc_now()
        with self.db.transaction() as conn:
            # 用临时表承载本轮见到的 ID，避免大目录产生超长 IN 参数列表。
            conn.execute("CREATE TEMP TABLE IF NOT EXISTS seen_ids (id INTEGER PRIMARY KEY)")
            conn.execute("DELETE FROM seen_ids")
            conn.executemany(
                "INSERT OR IGNORE INTO seen_ids(id) VALUES(?)",
                ((int(file_id),) for file_id in seen_ids),
            )
            affected = conn.execute(
                """
                SELECT DISTINCT f.video_id
                FROM video_files f JOIN videos v ON v.id = f.video_id
                WHERE v.root_id=? AND f.present=1 AND f.id NOT IN (SELECT id FROM seen_ids)
                """,
                (root_id,),
            ).fetchall()
            cur = conn.execute(
                """
                UPDATE video_files SET present=0, missing_since=?, updated_at=?
                WHERE video_id IN (SELECT id FROM videos WHERE root_id=?)
                  AND present=1 AND id NOT IN (SELECT id FROM seen_ids)
                """,
                (now, now, root_id),
            )
            for row in affected:
                self._refresh_video_from_files(conn, int(row["video_id"]))
            return cur.rowcount

    def list_videos(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        q: str | None = None,
        has_code: bool | None = None,
        scrape_status: str | None = None,
        present: bool | None = None,
        sort: str = "updated_at",
        complete: bool | None = None,
        favorite: bool | None = None,
        actress_id: int | None = None,
        tag: str | None = None,
        series: str | None = None,
        censored: str | None = None,
        scraped: bool | None = None,
        seed: int | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询视频摘要，返回 ``(items, total)``。"""
        conditions: list[str] = []
        params: list[Any] = []
        if q:
            # 关键词同时匹配任意文件名、路径、标题、番号和演员名。
            needle = f"%{q.strip()}%"
            conditions.append(
                "(v.filename LIKE ? OR v.path LIKE ? OR m.title LIKE ? OR m.series LIKE ? "
                "OR v.jav_code LIKE ? OR m.code LIKE ? "
                "OR EXISTS (SELECT 1 FROM video_files f WHERE f.video_id=v.id AND "
                "(f.filename LIKE ? OR f.path LIKE ?)) "
                "OR EXISTS (SELECT 1 FROM video_actresses va JOIN actresses a ON a.id=va.actress_id "
                "WHERE va.video_id=v.id AND a.name LIKE ?))"
            )
            params.extend(
                [needle, needle, needle, needle, needle, needle, needle, needle, needle]
            )
        if has_code is not None:
            conditions.append("v.jav_code IS NOT NULL" if has_code else "v.jav_code IS NULL")
        if present is not None:
            conditions.append("v.present=?" if present else "v.present=0")
            if present:
                params.append(1)
        if scrape_status:
            # 还没创建 metadata 行的视频也视为待刮削。
            if scrape_status == "pending":
                conditions.append("(m.scrape_status IS NULL OR m.scrape_status='pending')")
            else:
                conditions.append("m.scrape_status=?")
                params.append(scrape_status)
        if complete is not None:
            conditions.append("COALESCE(m.is_complete, 0)=?")
            params.append(1 if complete else 0)
        if favorite is not None:
            conditions.append("v.favorite=?")
            params.append(1 if favorite else 0)
        if actress_id is not None:
            conditions.append(
                "EXISTS (SELECT 1 FROM video_actresses va WHERE va.video_id=v.id AND va.actress_id=?)"
            )
            params.append(actress_id)
        if tag:
            # 标签和类型都以 JSON 数组存储，点击任意标签都应能筛出对应影片。
            conditions.append(
                "(EXISTS (SELECT 1 FROM json_each(m.tags) WHERE json_each.value=?) "
                "OR EXISTS (SELECT 1 FROM json_each(m.genres) WHERE json_each.value=?))"
            )
            params.extend([tag, tag])
        if series:
            conditions.append("m.series=?")
            params.append(series)
        if censored:
            conditions.append("m.censored=?")
            params.append(censored)
        if scraped is not None:
            # “已刮削”只认成功；no_match/failed/没有元数据都算未刮削。
            if scraped:
                conditions.append("m.scrape_status='success'")
            else:
                conditions.append("COALESCE(m.scrape_status, '') <> 'success'")

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        # sort 只作为白名单 key 使用，SQL 片段永远不来自用户输入。
        if sort == "random":
            # 种子作为乘法因子而不是偏移量：不同种子会真正改变顺序，
            # 同时同一 seed 下翻页顺序稳定，不会重复或漏项。
            seed_value = abs(int(seed or 0)) % 2_147_483_647 or 1
            order = f"((v.id * {seed_value}) % 2147483647) ASC, v.id ASC"
        else:
            order = SORT_ORDERS.get(sort, SORT_ORDERS["updated_at"])
        offset = (page - 1) * page_size

        base_sql = """
            SELECT v.id, v.path, v.filename, v.size_bytes, v.mtime, v.duration_sec,
                   v.screenshot, v.features, v.present, v.missing_since, v.favorite,
                   v.scan_status, v.created_at, v.updated_at,
                   (SELECT COUNT(*) FROM video_files f
                    WHERE f.video_id=v.id AND f.present=1) AS file_count,
                   m.video_id AS metadata_video_id, m.title, m.original_title, m.year,
                   m.code, m.cover_url, m.cover_local, m.scrape_status, m.source_name,
                   m.last_scraped_at, m.genres, m.tags, m.actresses, m.studio,
                   m.series, m.release_date, m.runtime_sec, m.censored, m.country,
                   m.is_complete
            FROM videos v
            LEFT JOIN metadata m ON m.video_id = v.id
        """
        # metadata 与 video 是一对一关系，LEFT JOIN 不会放大计数。
        count_sql = """
            SELECT COUNT(*) AS n FROM videos v
            LEFT JOIN metadata m ON m.video_id = v.id
        """
        with self.db.connection() as conn:
            total = int(conn.execute(count_sql + where, params).fetchone()["n"])
            rows = conn.execute(
                base_sql + where + f" ORDER BY {order} LIMIT ? OFFSET ?",
                [*params, page_size, offset],
            ).fetchall()
            # 批量补充演员，避免每一行单独查询。
            actress_map = self._actress_map(conn, [int(row["id"]) for row in rows])
        items = []
        for row in rows:
            summary = self._video_summary(row)
            summary["actresses"] = actress_map.get(summary["id"], [])
            items.append(summary)
        return items, total

    def get_video(self, video_id: int) -> dict[str, Any]:
        """获取视频详情，包含文件信息、元数据和演员列表。"""
        with self.db.connection() as conn:
            video = conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
            if video is None:
                raise NotFoundError("视频不存在")
            meta = conn.execute("SELECT * FROM metadata WHERE video_id=?", (video_id,)).fetchone()
            files = conn.execute(
                """
                SELECT id, path, filename, size_bytes, duration_sec, present, missing_since
                FROM video_files WHERE video_id=? ORDER BY present DESC, id ASC
                """,
                (video_id,),
            ).fetchall()
            actress_map = self._actress_map(conn, [video_id])
        data = _row_dict(video)
        data["features"] = _json_load(data.get("features"), {})
        data["present"] = bool(data["present"])
        data["favorite"] = bool(data["favorite"])
        data["file_count"] = sum(1 for file in files if file["present"])
        return {
            "video": data,
            "metadata": _metadata_dict(meta),
            "actresses": actress_map.get(video_id, []),
            "files": [
                {**dict(file), "present": bool(file["present"])} for file in files
            ],
        }

    def delete_video(self, video_id: int) -> None:
        """删除视频记录；关联元数据由外键级联清理。"""
        with self.db.connection() as conn:
            cur = conn.execute("DELETE FROM videos WHERE id=?", (video_id,))
        if cur.rowcount == 0:
            raise NotFoundError("视频不存在")

    def delete_video_files(self, video_id: int, file_ids: Iterable[int]) -> dict[str, Any]:
        """从磁盘删除分组中的指定文件，并同步清理数据库记录。

        删除部分文件时保留影片记录并重算主文件；全部文件都删除后移除影片。
        文件必须属于该视频且位于已配置的扫描目录内，避免误删任意路径。
        单个文件删除失败不会中断其他文件，失败项会原样返回给前端。
        """
        ids = sorted({int(file_id) for file_id in file_ids})
        if not ids:
            raise InvalidError("请选择要删除的文件")
        placeholders = ",".join("?" for _ in ids)
        removed: list[int] = []
        failed: list[dict[str, Any]] = []
        with self.db.connection() as conn:
            if not conn.execute("SELECT 1 FROM videos WHERE id=?", (video_id,)).fetchone():
                raise NotFoundError("视频不存在")
            files = conn.execute(
                f"SELECT id, path, filename FROM video_files WHERE video_id=? AND id IN ({placeholders})",
                [video_id, *ids],
            ).fetchall()
            roots = conn.execute("SELECT path_key FROM scan_roots").fetchall()
        if len(files) != len(ids):
            raise InvalidError("存在不属于该视频的文件")
        root_keys = [str(row["path_key"]) for row in roots]
        for file in files:
            path = str(file["path"])
            if not any(is_within(path_key(path), root_key) for root_key in root_keys):
                failed.append(
                    {
                        "id": int(file["id"]),
                        "filename": file["filename"],
                        "message": "文件不在扫描目录内，已跳过",
                    }
                )
                continue
            target = Path(path)
            if target.exists():
                try:
                    target.unlink()
                except OSError as exc:
                    failed.append(
                        {
                            "id": int(file["id"]),
                            "filename": file["filename"],
                            "message": f"删除失败: {exc}",
                        }
                    )
                    continue
            removed.append(int(file["id"]))

        remaining = 0
        record_deleted = False
        if removed:
            with self.db.transaction() as conn:
                conn.executemany(
                    "DELETE FROM video_files WHERE id=?",
                    ((file_id,) for file_id in removed),
                )
                remaining = int(
                    conn.execute(
                        "SELECT COUNT(*) AS n FROM video_files WHERE video_id=?", (video_id,)
                    ).fetchone()["n"]
                )
                if remaining == 0:
                    conn.execute("DELETE FROM videos WHERE id=?", (video_id,))
                    record_deleted = True
                else:
                    self._refresh_video_from_files(conn, video_id)
        else:
            with self.db.connection() as conn:
                remaining = int(
                    conn.execute(
                        "SELECT COUNT(*) AS n FROM video_files WHERE video_id=?", (video_id,)
                    ).fetchone()["n"]
                )
        return {
            "deleted_files": len(removed),
            "failed_files": failed,
            "remaining_files": remaining,
            "record_deleted": record_deleted,
        }

    def get_video_path(self, video_id: int, file_id: int | None = None) -> tuple[str, str]:
        """返回可播放文件的路径和文件名；缺失文件不允许播放。

        指定 ``file_id`` 时播放该分组下的特定文件；未指定且分组包含多个
        可用文件时抛出 ``multiple_files``，由前端弹出文件选择框。
        """
        with self.db.connection() as conn:
            if not conn.execute("SELECT 1 FROM videos WHERE id=?", (video_id,)).fetchone():
                raise NotFoundError("视频不存在")
            if file_id is not None:
                row = conn.execute(
                    "SELECT path, filename, present FROM video_files WHERE id=? AND video_id=?",
                    (file_id, video_id),
                ).fetchone()
                if row is None:
                    raise NotFoundError("文件不存在")
            else:
                rows = conn.execute(
                    """
                    SELECT path, filename, present FROM video_files
                    WHERE video_id=? ORDER BY present DESC, id ASC
                    """,
                    (video_id,),
                ).fetchall()
                present = [row for row in rows if row["present"]]
                if not present:
                    raise ConflictError("文件当前缺失，无法播放", code="path_not_found")
                if len(present) > 1:
                    raise ConflictError(
                        "该视频包含多个文件，请选择要播放的文件", code="multiple_files"
                    )
                row = present[0]
        if not row["present"]:
            raise ConflictError("文件当前缺失，无法播放", code="path_not_found")
        return row["path"], row["filename"]

    @staticmethod
    def _video_summary(row: Any) -> dict[str, Any]:
        """把视频与元数据的 JOIN 行拆成列表页需要的嵌套结构。"""
        data = _row_dict(row)
        features = _json_load(data.pop("features", None), {})
        metadata = None
        # LEFT JOIN 时用 metadata_video_id 判断元数据行是否真实存在。
        if data.pop("metadata_video_id", None) is not None:
            metadata = {
                "title": data.pop("title", None),
                "original_title": data.pop("original_title", None),
                "year": data.pop("year", None),
                "code": data.pop("code", None),
                "cover_url": data.pop("cover_url", None),
                "cover_local": data.pop("cover_local", None),
                "scrape_status": data.pop("scrape_status", None),
                "source_name": data.pop("source_name", None),
                "last_scraped_at": data.pop("last_scraped_at", None),
                "genres": _json_load(data.pop("genres", None), []),
                "tags": _json_load(data.pop("tags", None), []),
                "actresses": _json_load(data.pop("actresses", None), []),
                "studio": data.pop("studio", None),
                "series": data.pop("series", None),
                "release_date": data.pop("release_date", None),
                "runtime_sec": data.pop("runtime_sec", None),
                "censored": data.pop("censored", None),
                "country": data.pop("country", None),
                "is_complete": bool(data.pop("is_complete", 0)),
            }
        else:
            # 没有元数据行时，把 JOIN 带出的 NULL 列全部移除，避免混入视频字段。
            for key in (
                "title", "original_title", "year", "code", "cover_url", "cover_local",
                "scrape_status", "source_name", "last_scraped_at",
                "genres", "tags", "actresses", "studio", "release_date", "runtime_sec",
                "censored", "country", "is_complete",
            ):
                data.pop(key, None)
        data["features"] = features
        data["present"] = bool(data["present"])
        data["favorite"] = bool(data.get("favorite", 0))
        data["metadata"] = metadata
        return data

    @staticmethod
    def _actress_map(conn: Any, video_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
        """一次查询多部视频的演员，并以视频 ID 分组。"""
        if not video_ids:
            return {}
        placeholders = ",".join("?" for _ in video_ids)
        rows = conn.execute(
            f"SELECT va.video_id, a.id, a.name FROM video_actresses va "
            f"JOIN actresses a ON a.id=va.actress_id "
            f"WHERE va.video_id IN ({placeholders}) ORDER BY va.position ASC, a.id ASC",
            video_ids,
        ).fetchall()
        result: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            result.setdefault(int(row["video_id"]), []).append(
                {"id": int(row["id"]), "name": row["name"]}
            )
        return result

    def _ensure_metadata_row(self, conn: Any, video_id: int) -> Any:
        """确保视频有 metadata 行；没有则惰性创建空记录。"""
        row = conn.execute("SELECT * FROM metadata WHERE video_id=?", (video_id,)).fetchone()
        if row is not None:
            return row
        now = utc_now()
        conn.execute(
            "INSERT INTO metadata(video_id, manual_fields, scrape_status, version, "
            "is_complete, created_at, updated_at) VALUES(?, '[]', 'pending', 1, 0, ?, ?)",
            (video_id, now, now),
        )
        return conn.execute("SELECT * FROM metadata WHERE video_id=?", (video_id,)).fetchone()

    @staticmethod
    def _recompute_video_complete(conn: Any, video_id: int) -> None:
        """按固定字段集重算视频完整度并写回 metadata.is_complete。

        完整条件：标题、发行日期、本地封面均非空；有时长（元数据或文件探测值）；
        至少一个标签；至少一名关联演员。
        """
        conn.execute(
            """
            UPDATE metadata SET is_complete = CASE WHEN
                COALESCE(TRIM(title), '') <> ''
                AND COALESCE(TRIM(release_date), '') <> ''
                AND COALESCE(cover_local, '') <> ''
                AND (COALESCE(runtime_sec, 0) > 0 OR COALESCE(
                    (SELECT duration_sec FROM videos WHERE id=metadata.video_id), 0) > 0)
                AND COALESCE(json_array_length(tags), 0) > 0
                AND (SELECT COUNT(*) FROM video_actresses WHERE video_id=metadata.video_id) > 0
            THEN 1 ELSE 0 END
            WHERE video_id=?
            """,
            (video_id,),
        )

    @staticmethod
    def _recompute_actress_complete(conn: Any, actress_id: int) -> None:
        """重算演员完整度：姓名、生日、国籍、本地封面四项齐全才算完整。"""
        conn.execute(
            """
            UPDATE actresses SET is_complete = CASE WHEN
                COALESCE(TRIM(name), '') <> ''
                AND COALESCE(TRIM(birth_date), '') <> ''
                AND COALESCE(TRIM(nationality), '') <> ''
                AND COALESCE(TRIM(cover_local), '') <> ''
            THEN 1 ELSE 0 END
            WHERE id=?
            """,
            (actress_id,),
        )

    def _get_or_create_actress(
        self, conn: Any, name: str, profile_url: str | None = None
    ) -> int:
        """按规范化名称复用演员；不存在时创建，并只补充缺失的主页地址。"""
        key = actress_name_key(name)
        if not key:
            raise InvalidError("演员姓名不能为空")
        row = conn.execute("SELECT id FROM actresses WHERE name_key=?", (key,)).fetchone()
        if row is not None:
            if profile_url:
                # COALESCE 保证已有主页不会被后续来源覆盖。
                conn.execute(
                    "UPDATE actresses SET profile_url=COALESCE(profile_url, ?), updated_at=? "
                    "WHERE id=?",
                    (profile_url, utc_now(), row["id"]),
                )
            return int(row["id"])
        now = utc_now()
        cur = conn.execute(
            "INSERT INTO actresses(name, name_key, aliases, profile_url, manual_fields, "
            "created_at, updated_at) VALUES(?, ?, '[]', ?, '[]', ?, ?)",
            (name.strip(), key, profile_url, now, now),
        )
        actress_id = int(cur.lastrowid)
        self._recompute_actress_complete(conn, actress_id)
        return actress_id

    def _replace_video_actresses(
        self, conn: Any, video_id: int, refs: list[dict[str, Any]]
    ) -> None:
        """整体替换视频的演员关联，按出现顺序去重并重算完整度。"""
        conn.execute("DELETE FROM video_actresses WHERE video_id=?", (video_id,))
        seen: set[int] = set()
        position = 0
        for ref in refs:
            actress_id = ref.get("id")
            name = ref.get("name")
            profile_url = ref.get("url") or ref.get("profile_url")
            if actress_id is None:
                # 只给名字的演员按规范化名称查找或新建。
                if not isinstance(name, str) or not name.strip():
                    raise InvalidError("演员必须提供 id 或 name")
                actress_id = self._get_or_create_actress(conn, name, profile_url)
            else:
                row = conn.execute(
                    "SELECT id FROM actresses WHERE id=?", (int(actress_id),)
                ).fetchone()
                if row is None:
                    raise NotFoundError(f"演员不存在: {actress_id}")
                actress_id = int(actress_id)
                if profile_url:
                    conn.execute(
                        "UPDATE actresses SET profile_url=COALESCE(profile_url, ?), "
                        "updated_at=? WHERE id=?",
                        (str(profile_url), utc_now(), actress_id),
                    )
            # 同一部视频内重复出现的演员只保留第一次，position 保持输入顺序。
            if actress_id in seen:
                continue
            seen.add(actress_id)
            conn.execute(
                "INSERT INTO video_actresses(video_id, actress_id, position) VALUES(?, ?, ?)",
                (video_id, actress_id, position),
            )
            position += 1
        self._recompute_video_complete(conn, video_id)

    def update_video_metadata(
        self, video_id: int, fields: dict[str, Any], version: int
    ) -> dict[str, Any]:
        """手动更新视频元数据，使用版本号做乐观锁。

        被修改的字段会记入 ``manual_fields``，后续刮削默认不会覆盖它们；
        ``actresses`` 采用整体替换，其他字段按传入值更新。
        """
        allowed = {
            "title", "original_title", "overview", "release_date", "year", "runtime_sec",
            "genres", "tags", "code", "studio", "series", "director", "censored",
            "country", "actresses",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise InvalidError(f"未知字段: {', '.join(sorted(unknown))}")
        with self.db.transaction() as conn:
            video = conn.execute("SELECT id FROM videos WHERE id=?", (video_id,)).fetchone()
            if video is None:
                raise NotFoundError("视频不存在")
            existing = conn.execute(
                "SELECT * FROM metadata WHERE video_id=?", (video_id,)
            ).fetchone()
            # 已有元数据时必须匹配版本，防止并发编辑互相覆盖。
            if existing is not None and int(existing["version"]) != int(version):
                raise ConflictError(
                    "元数据已被修改，请刷新后重试", code="version_conflict"
                )
            self._ensure_metadata_row(conn, video_id)

            updates: dict[str, Any] = {}
            manual: list[str] = []
            for key, value in fields.items():
                if key == "actresses":
                    continue
                if key in {"genres", "tags"}:
                    if value is not None:
                        if not isinstance(value, list) or not all(
                            isinstance(item, str) for item in value
                        ):
                            raise InvalidError(f"{key} 必须是字符串数组")
                        value = json.dumps(value, ensure_ascii=False)
                elif key in {"year", "runtime_sec"}:
                    if value is not None and (
                        isinstance(value, bool) or not isinstance(value, int) or value < 0
                    ):
                        raise InvalidError(f"{key} 必须是非负整数")
                elif key == "censored":
                    if value not in {None, "censored", "uncensored", "unknown"}:
                        raise InvalidError("censored 必须是 censored/uncensored/unknown")
                else:
                    if value is not None:
                        if not isinstance(value, str):
                            raise InvalidError(f"{key} 必须是字符串")
                        value = value.strip() or None
                updates[key] = value
                manual.append(key)
            if updates:
                # 列名来自上面的 allowed 字段集合，值全部参数化。
                assignments = ", ".join(f"{key}=?" for key in updates)
                conn.execute(
                    f"UPDATE metadata SET {assignments}, version=version+1, updated_at=? "
                    f"WHERE video_id=?",
                    [*updates.values(), utc_now(), video_id],
                )
            if "actresses" in fields:
                refs = fields["actresses"] or []
                if not isinstance(refs, list):
                    raise InvalidError("actresses 必须是数组")
                self._replace_video_actresses(conn, video_id, refs)
                manual.append("actresses")
            if manual:
                row = conn.execute(
                    "SELECT manual_fields FROM metadata WHERE video_id=?", (video_id,)
                ).fetchone()
                current = _json_load(row["manual_fields"], [])
                for key in manual:
                    if key not in current:
                        current.append(key)
                conn.execute(
                    "UPDATE metadata SET manual_fields=?, version=version+1, updated_at=? "
                    "WHERE video_id=?",
                    (json.dumps(current, ensure_ascii=False), utc_now(), video_id),
                )
            else:
                # 没有实际字段变化也推进版本，保证客户端拿到的版本仍然前进。
                conn.execute(
                    "UPDATE metadata SET version=version+1, updated_at=? WHERE video_id=?",
                    (utc_now(), video_id),
                )
            self._recompute_video_complete(conn, video_id)
        return self.get_video(video_id)

    def set_video_favorite(self, video_id: int, favorite: bool) -> dict[str, Any]:
        """设置或取消视频收藏。"""
        with self.db.connection() as conn:
            cur = conn.execute(
                "UPDATE videos SET favorite=?, updated_at=? WHERE id=?",
                (int(favorite), utc_now(), video_id),
            )
        if cur.rowcount == 0:
            raise NotFoundError("视频不存在")
        return self.get_video(video_id)

    def update_video_cover(
        self, video_id: int, cover_local: str, cover_url: str | None = None
    ) -> dict[str, Any]:
        """更新视频封面。

        ``cover_local`` 是相对数据目录的路径（如 ``covers/videos/1.jpg``）；
        ``cover_url`` 为空时保留原有来源地址，只替换本地封面文件。
        本地封面会记入手动字段，避免之后的刮削覆盖用户选择。
        """
        with self.db.transaction() as conn:
            video = conn.execute("SELECT id FROM videos WHERE id=?", (video_id,)).fetchone()
            if video is None:
                raise NotFoundError("视频不存在")
            self._ensure_metadata_row(conn, video_id)
            if cover_url is None:
                conn.execute(
                    "UPDATE metadata SET cover_local=?, version=version+1, updated_at=? "
                    "WHERE video_id=?",
                    (cover_local, utc_now(), video_id),
                )
            else:
                conn.execute(
                    "UPDATE metadata SET cover_local=?, cover_url=?, version=version+1, "
                    "updated_at=? WHERE video_id=?",
                    (cover_local, cover_url, utc_now(), video_id),
                )
            row = conn.execute(
                "SELECT manual_fields FROM metadata WHERE video_id=?", (video_id,)
            ).fetchone()
            current = _json_load(row["manual_fields"], [])
            if "cover_local" not in current:
                current.append("cover_local")
            conn.execute(
                "UPDATE metadata SET manual_fields=? WHERE video_id=?",
                (json.dumps(current, ensure_ascii=False), video_id),
            )
            self._recompute_video_complete(conn, video_id)
        return self.get_video(video_id)

    def merge_video_result(
        self,
        video_id: int,
        fields: dict[str, Any],
        *,
        source_name: str,
        matched_by: str,
        actresses: list[str | dict[str, Any]] | None = None,
        raw_payload: str | None = None,
        overwrite_manual: bool = False,
    ) -> dict[str, Any]:
        """合并一次刮削结果。

        只接受白名单字段和 ``None`` 以外的值；默认保留手动编辑过的字段。
        无论是否实际更新字段，都会记录来源、匹配方式、原始响应和成功状态。
        """
        allowed = {
            "title", "original_title", "overview", "release_date", "year", "runtime_sec",
            "genres", "tags", "code", "studio", "series", "director", "censored",
            "country", "cover_url", "cover_local",
        }
        with self.db.transaction() as conn:
            video = conn.execute("SELECT id FROM videos WHERE id=?", (video_id,)).fetchone()
            if video is None:
                raise NotFoundError("视频不存在")
            meta = self._ensure_metadata_row(conn, video_id)
            manual = set(_json_load(meta["manual_fields"], []))
            filled_manual: set[str] = set()
            updates: dict[str, Any] = {}
            for key, value in fields.items():
                if key not in allowed or value is None:
                    continue
                # 手动字段默认不覆盖；但如果用户只是点过保存、字段仍为空，
                # 视为没有实际手动值，允许刮削补全。调用方要求覆盖时全部放行。
                if key in manual and not overwrite_manual:
                    if not _is_blank_value(meta[key]):
                        continue
                    # 空值被刮削补全后不再是有效的“手动值”，移除标记，
                    # 否则旧版本批量标记的手动字段会永久阻止后续更新。
                    filled_manual.add(key)
                if key in {"genres", "tags"}:
                    if isinstance(value, list):
                        value = json.dumps(value, ensure_ascii=False)
                updates[key] = value
            assignments = ", ".join(f"{key}=?" for key in updates)
            now = utc_now()
            if assignments:
                conn.execute(
                    f"UPDATE metadata SET {assignments}, source_name=?, matched_by=?, "
                    "raw_payload=?, scrape_status='success', last_scraped_at=?, "
                    "version=version+1, updated_at=? WHERE video_id=?",
                    [
                        *updates.values(),
                        source_name,
                        matched_by,
                        raw_payload,
                        now,
                        now,
                        video_id,
                    ],
                )
            else:
                # 没有可合并字段时仍更新刮削审计信息，避免前端一直显示未刮削。
                conn.execute(
                    "UPDATE metadata SET source_name=?, matched_by=?, raw_payload=?, "
                    "scrape_status='success', last_scraped_at=?, version=version+1, "
                    "updated_at=? WHERE video_id=?",
                    (source_name, matched_by, raw_payload, now, now, video_id),
                )
            # 演员列表不在 fields 白名单中，单独处理；手动填过演员时同样跳过，
            # 没有任何关联演员时允许刮削补全。
            existing_actresses = conn.execute(
                "SELECT COUNT(*) AS n FROM video_actresses WHERE video_id=?", (video_id,)
            ).fetchone()["n"]
            if actresses and (
                overwrite_manual or "actresses" not in manual or int(existing_actresses) == 0
            ):
                if "actresses" in manual and not overwrite_manual and int(existing_actresses) == 0:
                    filled_manual.add("actresses")
                refs: list[dict[str, Any]] = []
                for item in actresses:
                    if isinstance(item, str):
                        refs.append({"name": item})
                    elif isinstance(item, dict):
                        refs.append(item)
                self._replace_video_actresses(conn, video_id, refs)
            if filled_manual:
                remaining = [
                    key
                    for key in _json_load(meta["manual_fields"], [])
                    if key not in filled_manual
                ]
                conn.execute(
                    "UPDATE metadata SET manual_fields=? WHERE video_id=?",
                    (json.dumps(remaining, ensure_ascii=False), video_id),
                )
            self._recompute_video_complete(conn, video_id)
        return self.get_video(video_id)

    def mark_video_scrape_status(self, video_id: int, status: str) -> None:
        """只更新视频的刮削状态和时间戳，不修改元数据内容。"""
        with self.db.transaction() as conn:
            video = conn.execute("SELECT id FROM videos WHERE id=?", (video_id,)).fetchone()
            if video is None:
                raise NotFoundError("视频不存在")
            self._ensure_metadata_row(conn, video_id)
            conn.execute(
                "UPDATE metadata SET scrape_status=?, last_scraped_at=?, updated_at=? "
                "WHERE video_id=?",
                (status, utc_now(), utc_now(), video_id),
            )

    def merge_actress_result(
        self,
        actress_id: int,
        fields: dict[str, Any],
        *,
        source_name: str,
        raw_payload: str | None = None,
        overwrite_manual: bool = False,
    ) -> dict[str, Any]:
        """合并一次演员刮削结果，默认跳过手动编辑过的字段。"""
        allowed = {
            "aliases", "birth_date", "nationality", "cover_url", "cover_local",
            "profile_url", "height_cm", "bust_cm", "waist_cm", "hips_cm", "cup",
        }
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM actresses WHERE id=?", (actress_id,)).fetchone()
            if row is None:
                raise NotFoundError("演员不存在")
            manual = set(_json_load(row["manual_fields"], []))
            updates: dict[str, Any] = {}
            for key, value in fields.items():
                if key not in allowed or value is None:
                    continue
                if key in manual and not overwrite_manual:
                    continue
                if key == "aliases" and isinstance(value, list):
                    value = json.dumps(value, ensure_ascii=False)
                updates[key] = value
            assignments = ", ".join(f"{key}=?" for key in updates)
            now = utc_now()
            if assignments:
                conn.execute(
                    f"UPDATE actresses SET {assignments}, source_name=?, raw_payload=?, "
                    "version=version+1, updated_at=? WHERE id=?",
                    [*updates.values(), source_name, raw_payload, now, actress_id],
                )
            else:
                conn.execute(
                    "UPDATE actresses SET source_name=?, raw_payload=?, "
                    "version=version+1, updated_at=? WHERE id=?",
                    (source_name, raw_payload, now, actress_id),
                )
            self._recompute_actress_complete(conn, actress_id)
        return self.get_actress(actress_id)

    def list_video_ids_for_scrape(self, root_id: int, *, force: bool = False) -> list[int]:
        """列出目录下待刮削的视频 ID；force 为真时包含已完整的视频。"""
        sql = """
            SELECT v.id FROM videos v
            LEFT JOIN metadata m ON m.video_id=v.id
            WHERE v.present=1 AND v.root_id=?
        """
        params: list[Any] = [root_id]
        if not force:
            # 默认只取尚未完整的视频；没有 metadata 行的也视为未完整。
            sql += " AND COALESCE(m.is_complete, 0)=0"
        sql += " ORDER BY v.id ASC"
        with self.db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [int(row["id"]) for row in rows]

    def log_scrape(
        self,
        video_id: int,
        job_id: str | None,
        source_name: str,
        feature_used: str,
        success: bool,
        message: str,
    ) -> None:
        """追加一条刮削尝试日志，便于排查匹配失败原因。"""
        with self.db.connection() as conn:
            conn.execute(
                "INSERT INTO scrape_logs(video_id, job_id, source_name, feature_used, "
                "success, message, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
                (video_id, job_id, source_name, feature_used, int(success), message, utc_now()),
            )

    def list_scrape_logs(
        self, limit: int = 100, video_id: int | None = None
    ) -> list[dict[str, Any]]:
        """按时间倒序读取刮削日志，可按视频过滤。"""
        with self.db.connection() as conn:
            if video_id is None:
                rows = conn.execute(
                    "SELECT * FROM scrape_logs ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM scrape_logs WHERE video_id=? ORDER BY id DESC LIMIT ?",
                    (video_id, limit),
                ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------ actresses

    def list_actresses(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        q: str | None = None,
        complete: bool | None = None,
        favorite: bool | None = None,
        sort: str = "video_count",
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询演员列表，附带仍在库中的关联视频数量。"""
        conditions: list[str] = []
        params: list[Any] = []
        if q:
            # aliases 是 JSON 数组文本，LIKE 可直接覆盖其中的姓名片段。
            needle = f"%{q.strip()}%"
            conditions.append("(a.name LIKE ? OR a.aliases LIKE ?)")
            params.extend([needle, needle])
        if complete is not None:
            conditions.append("a.is_complete=?")
            params.append(1 if complete else 0)
        if favorite is not None:
            conditions.append("a.favorite=?")
            params.append(1 if favorite else 0)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        # 排序同样使用固定白名单片段，不拼接用户输入。
        order = {
            "video_count": "video_count DESC, a.name COLLATE NOCASE ASC",
            "name": "a.name COLLATE NOCASE ASC",
            "updated_at": "a.updated_at DESC",
            "birth_date": "a.birth_date DESC NULLS LAST",
        }.get(sort, "video_count DESC, a.name COLLATE NOCASE ASC")
        offset = (page - 1) * page_size
        # video_count 只统计 present=1 的视频，缺失文件不计入演员作品数。
        base_sql = """
            SELECT a.*,
                   (SELECT COUNT(*) FROM video_actresses va
                    JOIN videos v ON v.id=va.video_id
                    WHERE va.actress_id=a.id AND v.present=1) AS video_count
            FROM actresses a
        """
        count_sql = "SELECT COUNT(*) AS n FROM actresses a"
        with self.db.connection() as conn:
            total = int(conn.execute(count_sql + where, params).fetchone()["n"])
            rows = conn.execute(
                base_sql + where + f" ORDER BY {order} LIMIT ? OFFSET ?",
                [*params, page_size, offset],
            ).fetchall()
        return [self._actress_dict(row) for row in rows], total

    def get_actress(self, actress_id: int) -> dict[str, Any]:
        """获取演员详情及其关联视频列表。"""
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM actresses WHERE id=?", (actress_id,)).fetchone()
            if row is None:
                raise NotFoundError("演员不存在")
            # 作品数只计现存视频；详情列表则保留缺失记录供用户识别。
            count = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM video_actresses va JOIN videos v "
                    "ON v.id=va.video_id WHERE va.actress_id=? AND v.present=1",
                    (actress_id,),
                ).fetchone()["n"]
            )
            videos = conn.execute(
                """
                SELECT v.id, v.filename, v.path, v.present, v.favorite, v.updated_at,
                       m.title, m.year, m.release_date, m.cover_local, m.is_complete
                FROM video_actresses va
                JOIN videos v ON v.id=va.video_id
                LEFT JOIN metadata m ON m.video_id=v.id
                WHERE va.actress_id=?
                ORDER BY v.updated_at DESC
                """,
                (actress_id,),
            ).fetchall()
        actress = self._actress_dict(row)
        actress["video_count"] = count
        return {"actress": actress, "videos": [_row_dict(video) for video in videos]}

    def create_actress(self, name: str) -> dict[str, Any]:
        """按规范化姓名新建演员，拒绝重复。"""
        if not isinstance(name, str) or not name.strip():
            raise InvalidError("演员姓名不能为空")
        key = actress_name_key(name)
        now = utc_now()
        with self.db.transaction() as conn:
            if conn.execute("SELECT 1 FROM actresses WHERE name_key=?", (key,)).fetchone():
                raise ConflictError(f"演员已存在: {name.strip()}")
            cur = conn.execute(
                "INSERT INTO actresses(name, name_key, aliases, manual_fields, "
                "created_at, updated_at) VALUES(?, ?, '[]', '[]', ?, ?)",
                (name.strip(), key, now, now),
            )
            actress_id = int(cur.lastrowid)
            self._recompute_actress_complete(conn, actress_id)
        return self.get_actress(actress_id)

    def update_actress(
        self, actress_id: int, fields: dict[str, Any], version: int
    ) -> dict[str, Any]:
        """手动更新演员资料，使用版本号做乐观锁。

        改名时同步重算 name_key 并检查重复；所有被修改字段会记入手动字段，
        防止后续刮削覆盖。
        """
        allowed = {
            "name", "aliases", "birth_date", "nationality", "height_cm", "bust_cm",
            "waist_cm", "hips_cm", "cup", "profile_url",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise InvalidError(f"未知字段: {', '.join(sorted(unknown))}")
        with self.db.transaction() as conn:
            existing = conn.execute(
                "SELECT * FROM actresses WHERE id=?", (actress_id,)
            ).fetchone()
            if existing is None:
                raise NotFoundError("演员不存在")
            if int(existing["version"]) != int(version):
                raise ConflictError(
                    "演员资料已被修改，请刷新后重试", code="version_conflict"
                )
            updates: dict[str, Any] = {}
            manual: list[str] = []
            for key, value in fields.items():
                if key == "name":
                    if not isinstance(value, str) or not value.strip():
                        raise InvalidError("演员姓名不能为空")
                    value = value.strip()
                    new_key = actress_name_key(value)
                    # 改名后仍要保证规范化姓名全局唯一。
                    duplicate = conn.execute(
                        "SELECT 1 FROM actresses WHERE name_key=? AND id<>?",
                        (new_key, actress_id),
                    ).fetchone()
                    if duplicate:
                        raise ConflictError(f"演员已存在: {value}")
                    updates["name_key"] = new_key
                elif key == "aliases":
                    if value is not None:
                        if not isinstance(value, list) or not all(
                            isinstance(item, str) for item in value
                        ):
                            raise InvalidError("aliases 必须是字符串数组")
                        value = json.dumps(value, ensure_ascii=False)
                elif key in {"height_cm", "bust_cm", "waist_cm", "hips_cm"}:
                    if value is not None and (
                        isinstance(value, bool) or not isinstance(value, int) or value < 0
                    ):
                        raise InvalidError(f"{key} 必须是非负整数")
                else:
                    if value is not None:
                        if not isinstance(value, str):
                            raise InvalidError(f"{key} 必须是字符串")
                        value = value.strip() or None
                updates[key] = value
                manual.append(key)
            if updates:
                assignments = ", ".join(f"{key}=?" for key in updates)
                conn.execute(
                    f"UPDATE actresses SET {assignments}, version=version+1, updated_at=? "
                    f"WHERE id=?",
                    [*updates.values(), utc_now(), actress_id],
                )
            row = conn.execute(
                "SELECT manual_fields FROM actresses WHERE id=?", (actress_id,)
            ).fetchone()
            current = _json_load(row["manual_fields"], [])
            for key in manual:
                if key not in current:
                    current.append(key)
            conn.execute(
                "UPDATE actresses SET manual_fields=?, version=version+1, updated_at=? "
                "WHERE id=?",
                (json.dumps(current, ensure_ascii=False), utc_now(), actress_id),
            )
            self._recompute_actress_complete(conn, actress_id)
        return self.get_actress(actress_id)

    def delete_actress(self, actress_id: int) -> None:
        """删除没有关联视频的演员。"""
        with self.db.connection() as conn:
            row = conn.execute("SELECT id FROM actresses WHERE id=?", (actress_id,)).fetchone()
            if row is None:
                raise NotFoundError("演员不存在")
            linked = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM video_actresses WHERE actress_id=?",
                    (actress_id,),
                ).fetchone()["n"]
            )
            if linked:
                raise ConflictError("该演员仍有关联视频，无法删除")
            conn.execute("DELETE FROM actresses WHERE id=?", (actress_id,))

    def set_actress_favorite(self, actress_id: int, favorite: bool) -> dict[str, Any]:
        """设置或取消演员收藏。"""
        with self.db.connection() as conn:
            cur = conn.execute(
                "UPDATE actresses SET favorite=?, updated_at=? WHERE id=?",
                (int(favorite), utc_now(), actress_id),
            )
        if cur.rowcount == 0:
            raise NotFoundError("演员不存在")
        return self.get_actress(actress_id)

    def update_actress_cover(
        self, actress_id: int, cover_local: str, cover_url: str | None = None
    ) -> dict[str, Any]:
        """更新演员封面。

        ``cover_local`` 是相对数据目录的路径（如 ``covers/actresses/1.jpg``）；
        本地封面会被标记为手动字段，避免后续刮削覆盖。
        """
        with self.db.transaction() as conn:
            row = conn.execute("SELECT id FROM actresses WHERE id=?", (actress_id,)).fetchone()
            if row is None:
                raise NotFoundError("演员不存在")
            if cover_url is None:
                # 未提供新来源地址时保留原 cover_url，只换本地图片。
                conn.execute(
                    "UPDATE actresses SET cover_local=?, version=version+1, updated_at=? "
                    "WHERE id=?",
                    (cover_local, utc_now(), actress_id),
                )
            else:
                conn.execute(
                    "UPDATE actresses SET cover_local=?, cover_url=?, version=version+1, "
                    "updated_at=? WHERE id=?",
                    (cover_local, cover_url, utc_now(), actress_id),
                )
            row = conn.execute(
                "SELECT manual_fields FROM actresses WHERE id=?", (actress_id,)
            ).fetchone()
            current = _json_load(row["manual_fields"], [])
            if "cover_local" not in current:
                current.append("cover_local")
            conn.execute(
                "UPDATE actresses SET manual_fields=? WHERE id=?",
                (json.dumps(current, ensure_ascii=False), actress_id),
            )
            self._recompute_actress_complete(conn, actress_id)
        return self.get_actress(actress_id)

    @staticmethod
    def _actress_dict(row: Any) -> dict[str, Any]:
        """展开演员记录中的 JSON 列并转换布尔标志。"""
        data = _row_dict(row)
        data["aliases"] = _json_load(data.get("aliases"), [])
        data["manual_fields"] = _json_load(data.get("manual_fields"), [])
        data["favorite"] = bool(data["favorite"])
        data["is_complete"] = bool(data["is_complete"])
        return data

    # ---------------------------------------------------------------------- jobs

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


def _metadata_dict(row: Any) -> dict[str, Any] | None:
    """把 metadata 行转成 API 结构，展开 JSON 列并转换完整度标志。"""
    if row is None:
        return None
    data = _row_dict(row)
    data["genres"] = _json_load(data.get("genres"), [])
    data["tags"] = _json_load(data.get("tags"), [])
    data["actresses"] = _json_load(data.get("actresses"), [])
    data["manual_fields"] = _json_load(data.get("manual_fields"), [])
    data["is_complete"] = bool(data.get("is_complete", 0))
    return data


def _validate_interval(value: Any) -> None:
    """校验自动扫描间隔：0 表示关闭，最长 7 天。"""
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10080:
        raise InvalidError("自动扫描间隔必须是 0-10080 的整数（分钟）")


def _validate_settings_patch(patch: Any) -> None:
    """校验设置补丁的顶层结构，具体分组留给 validate_settings。"""
    if not isinstance(patch, dict):
        raise InvalidError("设置必须是 JSON 对象")
    unknown = set(patch) - SETTINGS_SECTIONS
    if unknown:
        raise InvalidError(f"未知的设置分组: {', '.join(sorted(unknown))}")


def validate_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """逐组校验设置，并顺手规范化扩展名和播放器路径。"""
    scan = settings.get("scan")
    if not isinstance(scan, dict):
        raise InvalidError("scan 设置必须是对象")
    allowed_scan = {"extensions", "ignore_globs", "min_size_mb", "follow_symlinks"}
    unknown = set(scan) - allowed_scan
    if unknown:
        raise InvalidError(f"未知的扫描设置: {', '.join(sorted(unknown))}")
    extensions = scan.get("extensions")
    if not isinstance(extensions, list) or not all(isinstance(ext, str) for ext in extensions):
        raise InvalidError("scan.extensions 必须是字符串数组")
    cleaned = []
    for ext in extensions:
        # 统一去掉前导点、转小写，并拒绝路径分隔符等非法字符。
        cleaned_ext = ext.strip().lower().lstrip(".")
        if not cleaned_ext or any(ch in cleaned_ext for ch in ".\\/ "):
            raise InvalidError(f"无效的扩展名: {ext}")
        cleaned.append(cleaned_ext)
    scan["extensions"] = sorted(set(cleaned))
    if not isinstance(scan.get("ignore_globs"), list) or not all(
        isinstance(item, str) for item in scan["ignore_globs"]
    ):
        raise InvalidError("scan.ignore_globs 必须是字符串数组")
    min_size = scan.get("min_size_mb")
    if isinstance(min_size, bool) or not isinstance(min_size, int) or min_size < 0:
        raise InvalidError("scan.min_size_mb 必须是非负整数")
    if not isinstance(scan.get("follow_symlinks"), bool):
        raise InvalidError("scan.follow_symlinks 必须是布尔值")

    scraping = settings.get("scraping")
    if not isinstance(scraping, dict):
        raise InvalidError("scraping 设置必须是对象")
    allowed_scraping = {"clean_rules", "workers", "cache_ttl_sec", "negative_ttl_sec"}
    unknown = set(scraping) - allowed_scraping
    if unknown:
        raise InvalidError(f"未知的刮削设置: {', '.join(sorted(unknown))}")
    rules = scraping.get("clean_rules")
    if not isinstance(rules, list) or not all(isinstance(rule, str) for rule in rules):
        raise InvalidError("scraping.clean_rules 必须是字符串数组")
    for rule in rules:
        # 提前编译，保存后才发现非法正则会导致刮削任务反复失败。
        try:
            re.compile(rule)
        except re.error as exc:
            raise InvalidError(f"无效的清洗正则 {rule!r}: {exc}") from exc
    workers = scraping.get("workers")
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 16:
        raise InvalidError("scraping.workers 必须是 1-16 的整数")
    for key in ("cache_ttl_sec", "negative_ttl_sec"):
        value = scraping.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise InvalidError(f"scraping.{key} 必须是非负整数")

    playback = settings.get("playback")
    if not isinstance(playback, dict):
        raise InvalidError("playback 设置必须是对象")
    allowed_playback = {"player"}
    unknown = set(playback) - allowed_playback
    if unknown:
        raise InvalidError(f"未知的播放设置: {', '.join(sorted(unknown))}")
    player = playback.get("player")
    if player is not None:
        if not isinstance(player, dict):
            raise InvalidError("playback.player 必须是对象或 null")
        unknown = set(player) - {"name", "path", "args"}
        if unknown:
            raise InvalidError(f"未知的播放器字段: {', '.join(sorted(unknown))}")
        if not isinstance(player.get("name"), str) or not player["name"].strip():
            raise InvalidError("playback.player.name 必须是非空字符串")
        path = player.get("path")
        if not isinstance(path, str) or not path.strip():
            raise InvalidError("playback.player.path 必须是非空字符串")
        # 保存前确认播放器真实存在，并把路径规范化为绝对路径。
        resolved = canonical_path(path)
        if not Path(resolved).is_file():
            raise InvalidError(f"播放器不存在: {resolved}")
        args = player.get("args", [])
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise InvalidError("playback.player.args 必须是字符串数组")
        player["path"] = resolved
        player["args"] = args
    return settings
