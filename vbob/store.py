from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from .config import DEFAULT_SETTINGS, deep_merge
from .db import Database, utc_now
from .errors import ConflictError, InvalidError, NotFoundError
from .paths import canonical_path, is_within, path_key
from .source_config import validate_source_config

SETTINGS_SECTIONS = {"scan", "scraping", "playback"}
SORT_ORDERS = {
    "updated_at": "v.updated_at DESC, v.id DESC",
    "filename": "v.filename COLLATE NOCASE ASC, v.id ASC",
    "year": "m.year DESC NULLS LAST, v.id DESC",
    "title": "m.title COLLATE NOCASE ASC NULLS LAST, v.id ASC",
    "code": "v.jav_code COLLATE NOCASE ASC NULLS LAST, v.id ASC",
}


def _row_dict(row: Any) -> dict[str, Any]:
    return dict(row)


def _json_load(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


class Store:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------ settings

    def get_settings(self) -> dict[str, Any]:
        with self.db.connection() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        stored: dict[str, Any] = {}
        for row in rows:
            try:
                stored[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                continue
        return deep_merge(DEFAULT_SETTINGS, stored)

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        _validate_settings_patch(patch)
        merged = deep_merge(self.get_settings(), patch)
        merged = validate_settings(merged)
        now = utc_now()
        with self.db.transaction() as conn:
            for section in SETTINGS_SECTIONS:
                conn.execute(
                    "INSERT INTO settings(key, value, updated_at) VALUES(?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (section, json.dumps(merged[section]), now),
                )
        return merged

    # --------------------------------------------------------------- scan roots

    def list_roots(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM scan_roots"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY id ASC"
        with self.db.connection() as conn:
            rows = conn.execute(sql).fetchall()
        return [self._root_dict(row) for row in rows]

    def get_root(self, root_id: int) -> dict[str, Any]:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM scan_roots WHERE id=?", (root_id,)).fetchone()
        if row is None:
            raise NotFoundError("扫描目录不存在")
        return self._root_dict(row)

    def create_root(self, path: str, enabled: bool = True) -> dict[str, Any]:
        resolved = canonical_path(path)
        key = path_key(resolved)
        if not Path(resolved).is_dir():
            raise InvalidError(f"目录不存在或不是目录: {resolved}")
        with self.db.connection() as conn:
            existing = conn.execute("SELECT id, path, path_key FROM scan_roots").fetchall()
        for row in existing:
            if row["path_key"] == key:
                raise ConflictError(f"扫描目录已存在: {row['path']}")
            if is_within(key, row["path_key"]) or is_within(row["path_key"], key):
                raise ConflictError(f"扫描目录与已有目录重叠: {row['path']}")
        now = utc_now()
        with self.db.connection() as conn:
            cur = conn.execute(
                "INSERT INTO scan_roots(path, path_key, enabled, created_at) VALUES(?, ?, ?, ?)",
                (resolved, key, int(enabled), now),
            )
        return self.get_root(int(cur.lastrowid))

    def update_root(self, root_id: int, *, enabled: bool) -> dict[str, Any]:
        self.get_root(root_id)
        with self.db.connection() as conn:
            conn.execute("UPDATE scan_roots SET enabled=? WHERE id=?", (int(enabled), root_id))
        return self.get_root(root_id)

    def delete_root(self, root_id: int) -> None:
        self.get_root(root_id)
        now = utc_now()
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE videos SET present=0, missing_since=?, updated_at=? WHERE root_id=?",
                (now, now, root_id),
            )
            conn.execute("DELETE FROM scan_roots WHERE id=?", (root_id,))

    def touch_root_scanned(self, root_id: int) -> None:
        with self.db.connection() as conn:
            conn.execute("UPDATE scan_roots SET last_scan_at=? WHERE id=?", (utc_now(), root_id))

    @staticmethod
    def _root_dict(row: Any) -> dict[str, Any]:
        data = _row_dict(row)
        data["enabled"] = bool(data["enabled"])
        return data

    # ------------------------------------------------------------------- sources

    def list_sources(self) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM sources ORDER BY priority ASC, name ASC"
            ).fetchall()
        return [self._source_dict(row) for row in rows]

    def get_source(self, source_id: int) -> dict[str, Any]:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        if row is None:
            raise NotFoundError("刮削源不存在")
        return self._source_dict(row)

    def create_source(self, config: dict[str, Any]) -> dict[str, Any]:
        normalized = validate_source_config(config)
        name = normalized["name"]
        with self.db.connection() as conn:
            if conn.execute("SELECT 1 FROM sources WHERE name=?", (name,)).fetchone():
                raise ConflictError(f"源名称已存在: {name}")
            now = utc_now()
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
        source = self.get_source(source_id)
        if source["builtin"]:
            raise ConflictError("内置源不可删除，只能禁用")
        with self.db.connection() as conn:
            conn.execute("DELETE FROM sources WHERE id=?", (source_id,))

    def update_source_state(
        self, source_id: int, *, enabled: bool | None = None, priority: int | None = None
    ) -> dict[str, Any]:
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
        data = _row_dict(row)
        data["config"] = _json_load(data.pop("config_json", None), {})
        data["enabled"] = bool(data["enabled"])
        data["builtin"] = bool(data["builtin"])
        return data

    # -------------------------------------------------------------------- videos

    def load_scan_cache(self, root_id: int) -> dict[str, dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT id, path_key, size_bytes, mtime, present FROM videos WHERE root_id=?",
                (root_id,),
            ).fetchall()
        return {row["path_key"]: dict(row) for row in rows}

    def upsert_video(
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
    ) -> int:
        now = utc_now()
        with self.db.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO videos(
                    root_id, path, path_key, filename, size_bytes, mtime, features,
                    present, scan_status, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(path_key) DO UPDATE SET
                    root_id=excluded.root_id,
                    path=excluded.path,
                    filename=excluded.filename,
                    size_bytes=excluded.size_bytes,
                    mtime=excluded.mtime,
                    features=excluded.features,
                    present=1,
                    missing_since=NULL,
                    scan_status=excluded.scan_status,
                    updated_at=excluded.updated_at
                RETURNING id
                """,
                (
                    root_id, path, key, filename, size, mtime,
                    json.dumps(features, ensure_ascii=False), scan_status, now, now,
                ),
            ).fetchone()
        return int(row["id"])

    def mark_seen(self, video_id: int) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE videos SET present=1, missing_since=NULL WHERE id=? AND present=0",
                (video_id,),
            )

    def mark_missing(self, root_id: int, seen_ids: Iterable[int]) -> int:
        now = utc_now()
        with self.db.transaction() as conn:
            conn.execute("CREATE TEMP TABLE IF NOT EXISTS seen_ids (id INTEGER PRIMARY KEY)")
            conn.execute("DELETE FROM seen_ids")
            conn.executemany(
                "INSERT OR IGNORE INTO seen_ids(id) VALUES(?)",
                ((int(video_id),) for video_id in seen_ids),
            )
            cur = conn.execute(
                """
                UPDATE videos SET present=0, missing_since=?, updated_at=?
                WHERE root_id=? AND present=1 AND id NOT IN (SELECT id FROM seen_ids)
                """,
                (now, now, root_id),
            )
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
    ) -> tuple[list[dict[str, Any]], int]:
        conditions: list[str] = []
        params: list[Any] = []
        if q:
            needle = f"%{q.strip()}%"
            conditions.append(
                "(v.filename LIKE ? OR v.path LIKE ? OR m.title LIKE ? OR v.jav_code LIKE ?)"
            )
            params.extend([needle, needle, needle, needle])
        if has_code is not None:
            conditions.append("v.jav_code IS NOT NULL" if has_code else "v.jav_code IS NULL")
        if present is not None:
            conditions.append("v.present=?" if present else "v.present=0")
            if present:
                params.append(1)
        if scrape_status:
            if scrape_status == "pending":
                conditions.append("(m.scrape_status IS NULL OR m.scrape_status='pending')")
            else:
                conditions.append("m.scrape_status=?")
                params.append(scrape_status)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        order = SORT_ORDERS.get(sort, SORT_ORDERS["updated_at"])
        offset = (page - 1) * page_size

        base_sql = """
            SELECT v.id, v.path, v.filename, v.size_bytes, v.mtime, v.duration_sec,
                   v.screenshot, v.features, v.present, v.missing_since,
                   v.scan_status, v.created_at, v.updated_at,
                   m.video_id AS metadata_video_id, m.title, m.original_title, m.year,
                   m.code, m.cover_url, m.cover_local, m.scrape_status, m.source_name,
                   m.last_scraped_at, m.genres, m.tags, m.actresses, m.studio,
                   m.release_date, m.runtime_sec
            FROM videos v
            LEFT JOIN metadata m ON m.video_id = v.id
        """
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
        return [self._video_summary(row) for row in rows], total

    def get_video(self, video_id: int) -> dict[str, Any]:
        with self.db.connection() as conn:
            video = conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
            if video is None:
                raise NotFoundError("视频不存在")
            meta = conn.execute("SELECT * FROM metadata WHERE video_id=?", (video_id,)).fetchone()
        data = _row_dict(video)
        data["features"] = _json_load(data.get("features"), {})
        data["present"] = bool(data["present"])
        return {"video": data, "metadata": _metadata_dict(meta)}

    def delete_video(self, video_id: int) -> None:
        with self.db.connection() as conn:
            cur = conn.execute("DELETE FROM videos WHERE id=?", (video_id,))
        if cur.rowcount == 0:
            raise NotFoundError("视频不存在")

    def get_video_path(self, video_id: int) -> tuple[str, str]:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT path, filename, present FROM videos WHERE id=?", (video_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError("视频不存在")
        if not row["present"]:
            raise ConflictError("文件当前缺失，无法播放", code="path_not_found")
        return row["path"], row["filename"]

    @staticmethod
    def _video_summary(row: Any) -> dict[str, Any]:
        data = _row_dict(row)
        features = _json_load(data.pop("features", None), {})
        metadata = None
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
                "release_date": data.pop("release_date", None),
                "runtime_sec": data.pop("runtime_sec", None),
            }
        else:
            for key in (
                "title", "original_title", "year", "code", "cover_url", "cover_local",
                "scrape_status", "source_name", "last_scraped_at",
                "genres", "tags", "actresses", "studio", "release_date", "runtime_sec",
            ):
                data.pop(key, None)
        data["features"] = features
        data["present"] = bool(data["present"])
        data["metadata"] = metadata
        return data

    # ---------------------------------------------------------------------- jobs

    def create_job(self, job_id: str, job_type: str, payload: dict[str, Any]) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "INSERT INTO jobs(id, type, status, payload, created_at) VALUES(?, ?, 'queued', ?, ?)",
                (job_id, job_type, json.dumps(payload, ensure_ascii=False), utc_now()),
            )

    def update_job(self, job_id: str, **fields: Any) -> None:
        allowed = {"status", "total", "done", "failed", "message", "started_at", "finished_at"}
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
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise NotFoundError("任务不存在")
        data = _row_dict(row)
        data["payload"] = _json_load(data.get("payload"), {})
        data["cancel_requested"] = bool(data["cancel_requested"])
        return data

    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        result = []
        for row in rows:
            data = _row_dict(row)
            data["payload"] = _json_load(data.get("payload"), {})
            data["cancel_requested"] = bool(data["cancel_requested"])
            result.append(data)
        return result

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job["status"] in {"succeeded", "failed", "canceled"}:
            return job
        with self.db.connection() as conn:
            conn.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (job_id,))
        return self.get_job(job_id)

    def cancel_queued_job(self, job_id: str) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE jobs SET status='canceled', finished_at=?, message=? "
                "WHERE id=? AND status='queued'",
                (utc_now(), "任务已取消", job_id),
            )

    def recover_orphan_jobs(self) -> int:
        with self.db.connection() as conn:
            cur = conn.execute(
                "UPDATE jobs SET status='failed', finished_at=?, message=? "
                "WHERE status IN ('queued', 'running')",
                (utc_now(), "服务重启，任务中断"),
            )
            return cur.rowcount


def _metadata_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    data = _row_dict(row)
    data["genres"] = _json_load(data.get("genres"), [])
    data["tags"] = _json_load(data.get("tags"), [])
    data["actresses"] = _json_load(data.get("actresses"), [])
    data["manual_fields"] = _json_load(data.get("manual_fields"), [])
    return data


def _validate_settings_patch(patch: Any) -> None:
    if not isinstance(patch, dict):
        raise InvalidError("设置必须是 JSON 对象")
    unknown = set(patch) - SETTINGS_SECTIONS
    if unknown:
        raise InvalidError(f"未知的设置分组: {', '.join(sorted(unknown))}")


def validate_settings(settings: dict[str, Any]) -> dict[str, Any]:
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
        resolved = canonical_path(path)
        if not Path(resolved).is_file():
            raise InvalidError(f"播放器不存在: {resolved}")
        args = player.get("args", [])
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise InvalidError("playback.player.args 必须是字符串数组")
        player["path"] = resolved
        player["args"] = args
    return settings
