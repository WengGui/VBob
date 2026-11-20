"""元数据合并、封面、分类与刮削日志。"""

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


class MetadataMixin:
    """元数据合并、封面、分类与刮削日志。"""

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

    def set_video_category(self, video_id: int, category: str) -> dict[str, Any]:
        """手动修改视频分类；之后目录改分类不会再覆盖该视频。"""
        category = normalize_category(category)
        with self.db.connection() as conn:
            cur = conn.execute(
                "UPDATE videos SET category=?, category_manual=1, updated_at=? WHERE id=?",
                (category, utc_now(), video_id),
            )
        if cur.rowcount == 0:
            raise NotFoundError("视频不存在")
        return self.get_video(video_id)

    def set_source_preference(
        self, video_id: int, source_id: int | None
    ) -> dict[str, Any]:
        """记录或清除视频偏好的刮削源；None 表示恢复跟随目录/分类配置。"""
        with self.db.transaction() as conn:
            video = conn.execute("SELECT id FROM videos WHERE id=?", (video_id,)).fetchone()
            if video is None:
                raise NotFoundError("视频不存在")
            if source_id is not None:
                source = conn.execute(
                    "SELECT id FROM sources WHERE id=?", (source_id,)
                ).fetchone()
                if source is None:
                    raise NotFoundError("刮削源不存在")
            self._ensure_metadata_row(conn, video_id)
            conn.execute(
                "UPDATE metadata SET source_id=?, version=version+1, updated_at=? "
                "WHERE video_id=?",
                (source_id, utc_now(), video_id),
            )
        return self.get_video(video_id)

    def category_counts(self) -> dict[str, int]:
        """各分类的可见视频数量；没有记录的分类返回 0，all 为合计。"""
        counts: dict[str, int] = {value: 0 for value in CATEGORY_VALUES}
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT category, COUNT(*) AS n FROM videos WHERE present=1 "
                "GROUP BY category"
            ).fetchall()
        for row in rows:
            key = str(row["category"] or DEFAULT_CATEGORY)
            counts[key] = counts.get(key, 0) + int(row["n"])
        counts["all"] = sum(counts[value] for value in CATEGORY_VALUES)
        return counts

    def clear_scraped_fields(self, video_id: int) -> None:
        """清空非手动维护的刮削字段，供切换源时完整重刮。"""
        fields = (
            "title", "original_title", "overview", "cover_url", "cover_local",
            "year", "release_date", "runtime_sec", "genres", "tags", "code",
            "studio", "series", "director", "censored", "country",
        )
        with self.db.transaction() as conn:
            meta = conn.execute(
                "SELECT * FROM metadata WHERE video_id=?", (video_id,)
            ).fetchone()
            if meta is None:
                return
            manual = set(_json_load(meta["manual_fields"], []))
            updates = {key: None for key in fields if key not in manual}
            conn.execute(
                "UPDATE metadata SET source_name=NULL, source_names='[]', matched_by=NULL, "
                "raw_payload=NULL, scrape_status='pending', version=version+1, "
                "updated_at=? WHERE video_id=?",
                (utc_now(), video_id),
            )
            if updates:
                assignments = ", ".join(f"{key}=?" for key in updates)
                conn.execute(
                    f"UPDATE metadata SET {assignments} WHERE video_id=?",
                    [*updates.values(), video_id],
                )
            # 演员不是手动维护时一并清空，随后由刮削重新写入。
            if "actresses" not in manual:
                conn.execute("DELETE FROM video_actresses WHERE video_id=?", (video_id,))
            self._recompute_video_complete(conn, video_id)

    def update_video_cover(
        self,
        video_id: int,
        cover_local: str,
        cover_url: str | None = None,
        *,
        mark_manual: bool = True,
    ) -> dict[str, Any]:
        """更新视频封面。

        ``cover_local`` 是相对数据目录的路径（如 ``covers/videos/1.jpg``）；
        ``cover_url`` 为空时保留原有来源地址，只替换本地封面文件。
        ``mark_manual`` 为真时记入手动字段，避免之后的刮削覆盖用户选择；
        从刮削地址重新下载时应传 False。
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
            if mark_manual:
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
        source_names: list[str] | None = None,
        actresses: list[str | dict[str, Any]] | None = None,
        raw_payload: str | None = None,
        overwrite_manual: bool = False,
    ) -> dict[str, Any]:
        """合并一次刮削结果。

        只接受白名单字段和 ``None`` 以外的值；默认保留手动编辑过的字段。
        无论是否实际更新字段，都会记录来源、匹配方式、原始响应和成功状态。
        ``source_names`` 记录本次实际贡献数据的全部源，按执行顺序排列。
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
            names = list(source_names or [source_name])
            names_json = json.dumps(names, ensure_ascii=False)
            if assignments:
                conn.execute(
                    f"UPDATE metadata SET {assignments}, source_name=?, source_names=?, "
                    "matched_by=?, raw_payload=?, scrape_status='success', "
                    "last_scraped_at=?, version=version+1, updated_at=? WHERE video_id=?",
                    [
                        *updates.values(),
                        source_name,
                        names_json,
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
                    "UPDATE metadata SET source_name=?, source_names=?, matched_by=?, "
                    "raw_payload=?, scrape_status='success', last_scraped_at=?, "
                    "version=version+1, updated_at=? WHERE video_id=?",
                    (source_name, names_json, matched_by, raw_payload, now, now, video_id),
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
