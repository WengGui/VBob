"""演员资料与收藏。"""

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


class ActressMixin:
    """演员资料与收藏。"""

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

    def get_actress_cover_path(self, actress_id: int) -> str | None:
        """只查询演员封面相对路径，供图片接口使用；演员不存在返回 404。"""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT cover_local FROM actresses WHERE id=?", (actress_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError("演员不存在")
        return row["cover_local"]

    def delete_actress(self, actress_id: int) -> None:
        """删除没有关联视频的演员，并清理本地封面文件。"""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT id, cover_local FROM actresses WHERE id=?", (actress_id,)
            ).fetchone()
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
        remove_local_images(getattr(self, "data_dir", None), [row["cover_local"]])

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
