from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

from .config import DEFAULT_SETTINGS, deep_merge
from .db import Database, utc_now
from .errors import ConflictError, InvalidError, NotFoundError
from .names import actress_name_key
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

    ROOT_SELECT = """
        SELECT r.*,
               (SELECT COUNT(*) FROM videos v WHERE v.root_id=r.id AND v.present=1)
                   AS scanned_count,
               (SELECT COUNT(*) FROM videos v JOIN metadata m ON m.video_id=v.id
                WHERE v.root_id=r.id AND v.present=1 AND m.is_complete=1)
                   AS scraped_count
        FROM scan_roots r
    """

    def list_roots(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
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
                    old_base = root["path"]
                    videos = conn.execute(
                        "SELECT id, path FROM videos WHERE root_id=?", (root_id,)
                    ).fetchall()
                    planned: list[tuple[int, str, str]] = []
                    for video in videos:
                        relative = os.path.relpath(video["path"], old_base)
                        if relative.startswith(".."):
                            continue
                        new_path = canonical_path(os.path.join(resolved, relative))
                        planned.append((int(video["id"]), new_path, path_key(new_path)))
                    for _, _, key in planned:
                        conflict = conn.execute(
                            "SELECT 1 FROM videos WHERE path_key=? AND root_id<>?",
                            (key, root_id),
                        ).fetchone()
                        if conflict:
                            raise ConflictError("修改目录后存在路径冲突，请先清理重复记录")
                    conn.execute(
                        "UPDATE scan_roots SET path=?, path_key=? WHERE id=?",
                        (resolved, new_key, root_id),
                    )
                    for video_id, new_path, new_path_key in planned:
                        conn.execute(
                            "UPDATE videos SET path=?, path_key=?, updated_at=? WHERE id=?",
                            (new_path, new_path_key, utc_now(), video_id),
                        )
            updates: list[str] = []
            params: list[Any] = []
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

    def delete_root(self, root_id: int) -> None:
        self.get_root(root_id)
        now = utc_now()
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE videos SET present=0, missing_since=?, updated_at=? WHERE root_id=?",
                (now, now, root_id),
            )
            conn.execute("DELETE FROM scan_roots WHERE id=?", (root_id,))

    def start_root_scan(self, root_id: int) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE scan_roots SET last_scan_status='running', last_scan_started_at=?, "
                "last_scan_finished_at=NULL, last_scan_duration_ms=NULL WHERE id=?",
                (utc_now(), root_id),
            )

    def finish_root_scan(self, root_id: int, status: str, duration_ms: int) -> None:
        now = utc_now()
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE scan_roots SET last_scan_status=?, last_scan_finished_at=?, "
                "last_scan_duration_ms=?, last_scan_at=?, last_scan_started_at=COALESCE("
                "last_scan_started_at, ?) WHERE id=?",
                (status, now, duration_ms, now, now, root_id),
            )

    def touch_root_scanned(self, root_id: int) -> None:
        with self.db.connection() as conn:
            conn.execute("UPDATE scan_roots SET last_scan_at=? WHERE id=?", (utc_now(), root_id))

    @staticmethod
    def _active_jobs(conn: Any, root_ids: list[int]) -> dict[int, dict[str, Any]]:
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
        data = _row_dict(row)
        data["enabled"] = bool(data["enabled"])
        data["scan_interval_minutes"] = int(data.get("scan_interval_minutes") or 0)
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
        complete: bool | None = None,
        favorite: bool | None = None,
        actress_id: int | None = None,
        tag: str | None = None,
        censored: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        conditions: list[str] = []
        params: list[Any] = []
        if q:
            needle = f"%{q.strip()}%"
            conditions.append(
                "(v.filename LIKE ? OR v.path LIKE ? OR m.title LIKE ? OR v.jav_code LIKE ? "
                "OR EXISTS (SELECT 1 FROM video_actresses va JOIN actresses a ON a.id=va.actress_id "
                "WHERE va.video_id=v.id AND a.name LIKE ?))"
            )
            params.extend([needle, needle, needle, needle, needle])
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
            conditions.append("EXISTS (SELECT 1 FROM json_each(m.tags) WHERE json_each.value=?)")
            params.append(tag)
        if censored:
            conditions.append("m.censored=?")
            params.append(censored)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        order = SORT_ORDERS.get(sort, SORT_ORDERS["updated_at"])
        offset = (page - 1) * page_size

        base_sql = """
            SELECT v.id, v.path, v.filename, v.size_bytes, v.mtime, v.duration_sec,
                   v.screenshot, v.features, v.present, v.missing_since, v.favorite,
                   v.scan_status, v.created_at, v.updated_at,
                   m.video_id AS metadata_video_id, m.title, m.original_title, m.year,
                   m.code, m.cover_url, m.cover_local, m.scrape_status, m.source_name,
                   m.last_scraped_at, m.genres, m.tags, m.actresses, m.studio,
                   m.release_date, m.runtime_sec, m.censored, m.country, m.is_complete
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
            actress_map = self._actress_map(conn, [int(row["id"]) for row in rows])
        items = []
        for row in rows:
            summary = self._video_summary(row)
            summary["actresses"] = actress_map.get(summary["id"], [])
            items.append(summary)
        return items, total

    def get_video(self, video_id: int) -> dict[str, Any]:
        with self.db.connection() as conn:
            video = conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
            if video is None:
                raise NotFoundError("视频不存在")
            meta = conn.execute("SELECT * FROM metadata WHERE video_id=?", (video_id,)).fetchone()
            actress_map = self._actress_map(conn, [video_id])
        data = _row_dict(video)
        data["features"] = _json_load(data.get("features"), {})
        data["present"] = bool(data["present"])
        data["favorite"] = bool(data["favorite"])
        return {
            "video": data,
            "metadata": _metadata_dict(meta),
            "actresses": actress_map.get(video_id, []),
        }

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
                "censored": data.pop("censored", None),
                "country": data.pop("country", None),
                "is_complete": bool(data.pop("is_complete", 0)),
            }
        else:
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
        key = actress_name_key(name)
        if not key:
            raise InvalidError("演员姓名不能为空")
        row = conn.execute("SELECT id FROM actresses WHERE name_key=?", (key,)).fetchone()
        if row is not None:
            if profile_url:
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
        conn.execute("DELETE FROM video_actresses WHERE video_id=?", (video_id,))
        seen: set[int] = set()
        position = 0
        for ref in refs:
            actress_id = ref.get("id")
            name = ref.get("name")
            profile_url = ref.get("url") or ref.get("profile_url")
            if actress_id is None:
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
                conn.execute(
                    "UPDATE metadata SET version=version+1, updated_at=? WHERE video_id=?",
                    (utc_now(), video_id),
                )
            self._recompute_video_complete(conn, video_id)
        return self.get_video(video_id)

    def set_video_favorite(self, video_id: int, favorite: bool) -> dict[str, Any]:
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
            updates: dict[str, Any] = {}
            for key, value in fields.items():
                if key not in allowed or value is None:
                    continue
                if key in manual and not overwrite_manual:
                    continue
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
                conn.execute(
                    "UPDATE metadata SET source_name=?, matched_by=?, raw_payload=?, "
                    "scrape_status='success', last_scraped_at=?, version=version+1, "
                    "updated_at=? WHERE video_id=?",
                    (source_name, matched_by, raw_payload, now, now, video_id),
                )
            if actresses and "actresses" not in manual:
                refs: list[dict[str, Any]] = []
                for item in actresses:
                    if isinstance(item, str):
                        refs.append({"name": item})
                    elif isinstance(item, dict):
                        refs.append(item)
                self._replace_video_actresses(conn, video_id, refs)
            self._recompute_video_complete(conn, video_id)
        return self.get_video(video_id)

    def mark_video_scrape_status(self, video_id: int, status: str) -> None:
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
        sql = """
            SELECT v.id FROM videos v
            LEFT JOIN metadata m ON m.video_id=v.id
            WHERE v.present=1 AND v.root_id=?
        """
        params: list[Any] = [root_id]
        if not force:
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
        with self.db.connection() as conn:
            conn.execute(
                "INSERT INTO scrape_logs(video_id, job_id, source_name, feature_used, "
                "success, message, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
                (video_id, job_id, source_name, feature_used, int(success), message, utc_now()),
            )

    def list_scrape_logs(
        self, limit: int = 100, video_id: int | None = None
    ) -> list[dict[str, Any]]:
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
        conditions: list[str] = []
        params: list[Any] = []
        if q:
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
        order = {
            "video_count": "video_count DESC, a.name COLLATE NOCASE ASC",
            "name": "a.name COLLATE NOCASE ASC",
            "updated_at": "a.updated_at DESC",
            "birth_date": "a.birth_date DESC NULLS LAST",
        }.get(sort, "video_count DESC, a.name COLLATE NOCASE ASC")
        offset = (page - 1) * page_size
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
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM actresses WHERE id=?", (actress_id,)).fetchone()
            if row is None:
                raise NotFoundError("演员不存在")
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
        with self.db.transaction() as conn:
            row = conn.execute("SELECT id FROM actresses WHERE id=?", (actress_id,)).fetchone()
            if row is None:
                raise NotFoundError("演员不存在")
            if cover_url is None:
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
        with self.db.connection() as conn:
            conn.execute(
                "INSERT INTO jobs(id, type, status, payload, root_id, created_at) "
                "VALUES(?, ?, 'queued', ?, ?, ?)",
                (job_id, job_type, json.dumps(payload, ensure_ascii=False), root_id, utc_now()),
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

    def list_jobs(self, limit: int = 20, root_id: int | None = None) -> list[dict[str, Any]]:
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
    data["is_complete"] = bool(data.get("is_complete", 0))
    return data


def _validate_interval(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10080:
        raise InvalidError("自动扫描间隔必须是 0-10080 的整数（分钟）")


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
