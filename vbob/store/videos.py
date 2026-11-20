"""视频、文件分组、扫描缓存与删除。"""

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


class VideoMixin:
    """视频、文件分组、扫描缓存与删除。"""

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

    def detach_video_files(
        self, video_id: int, file_ids: Iterable[int]
    ) -> dict[str, Any]:
        """把分组中的文件拆成独立视频，用于撤销误合并。

        每个文件会创建一条新的视频记录（无元数据），并标记
        ``manual_separate``，避免下次启动时被自动剧集规则再次合并。
        至少需要保留一个文件在原视频中。
        """
        ids = sorted({int(file_id) for file_id in file_ids})
        if not ids:
            raise InvalidError("请选择要移出剧集的文件")
        placeholders = ",".join("?" for _ in ids)
        new_ids: list[int] = []
        now = utc_now()
        pipeline = FeaturePipeline()
        with self.db.transaction() as conn:
            video = conn.execute(
                "SELECT id, root_id, category, category_manual FROM videos WHERE id=?",
                (video_id,),
            ).fetchone()
            if video is None:
                raise NotFoundError("视频不存在")
            total_files = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM video_files WHERE video_id=?", (video_id,)
                ).fetchone()["n"]
            )
            files = conn.execute(
                f"""
                SELECT id, path, path_key, filename, size_bytes, mtime, duration_sec,
                       present, missing_since
                FROM video_files WHERE video_id=? AND id IN ({placeholders})
                """,
                [video_id, *ids],
            ).fetchall()
            if len(files) != len(ids):
                raise InvalidError("存在不属于该视频的文件")
            if len(files) >= total_files:
                raise InvalidError("至少需要在原视频中保留一个文件")

            root_path = None
            if video["root_id"] is not None:
                root = conn.execute(
                    "SELECT path FROM scan_roots WHERE id=?", (int(video["root_id"]),)
                ).fetchone()
                root_path = str(root["path"]) if root else None

            # 原视频的主 path_key 可能正好是要拆出去的文件，先让出唯一键。
            conn.execute(
                "UPDATE videos SET path_key=? WHERE id=?",
                (f"__detach__{video_id}_{now}", video_id),
            )
            for file in files:
                rel_path = str(file["filename"])
                dirs: tuple[str, ...] = ()
                if root_path:
                    rel_path = os.path.relpath(str(file["path"]), root_path)
                    parent = os.path.dirname(rel_path)
                    dirs = tuple(reversed(parent.split(os.sep))) if parent else ()
                try:
                    features = pipeline.extract(
                        FileRef(
                            filename=str(file["filename"]),
                            rel_path=rel_path,
                            dirs=dirs,
                        )
                    )
                except Exception:  # noqa: BLE001 - 提取失败也要允许移出
                    log.exception("detach feature extraction failed for %s", file["filename"])
                    features = {}
                features["manual_separate"] = True
                cur = conn.execute(
                    """
                    INSERT INTO videos(
                        root_id, path, path_key, filename, size_bytes, mtime,
                        duration_sec, features, category, category_manual,
                        present, missing_since, scan_status, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scanned', ?, ?)
                    """,
                    (
                        video["root_id"],
                        file["path"],
                        file["path_key"],
                        file["filename"],
                        file["size_bytes"],
                        file["mtime"],
                        file["duration_sec"],
                        json.dumps(features, ensure_ascii=False),
                        video["category"],
                        int(video["category_manual"]),
                        int(file["present"]),
                        file["missing_since"],
                        now,
                        now,
                    ),
                )
                new_id = int(cur.lastrowid)
                conn.execute(
                    "UPDATE video_files SET video_id=? WHERE id=?",
                    (new_id, int(file["id"])),
                )
                new_ids.append(new_id)
            self._refresh_video_from_files(conn, video_id)
        return {"detached": new_ids, "video": self.get_video(video_id)}

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
                  AND COALESCE(json_extract(v.features, '$.manual_separate'), 0) = 0
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
        category: str = DEFAULT_CATEGORY,
    ) -> tuple[int, int, bool]:
        """新增或刷新一个视频文件，返回 ``(video_id, file_id, created)``。

        有番号的同一目录文件会挂到同一个 videos 分组下；没有番号的文件
        每个都是独立分组。已存在的文件复用原记录，从而保留元数据和收藏。
        新视频继承目录分类；已存在且未被手动改过分类的视频随目录更新。
        """
        category = normalize_category(category)
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
                    # 重新提取特征时保留手动“移出剧集”标记，避免文件变化后
                    # 下次启动又被自动规则并回剧集。
                    updated_features = dict(features)
                    if old_features.get("manual_separate"):
                        updated_features["manual_separate"] = True
                    conn.execute(
                        "UPDATE videos SET root_id=?, features=?, scan_status=?, "
                        "category=CASE WHEN category_manual=0 THEN ? ELSE category END, "
                        "updated_at=? WHERE id=?",
                        (
                            root_id,
                            json.dumps(updated_features, ensure_ascii=False),
                            scan_status,
                            category,
                            now,
                            video_id,
                        ),
                    )
                else:
                    conn.execute(
                        "UPDATE videos SET root_id=?, scan_status=?, "
                        "category=CASE WHEN category_manual=0 THEN ? ELSE category END, "
                        "updated_at=? WHERE id=?",
                        (root_id, scan_status, category, now, video_id),
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
                    WHERE root_id=?
                      AND COALESCE(json_extract(features, '$.manual_separate'), 0) = 0
                      AND COALESCE(
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
                    category, present, scan_status, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (root_id, path, key, filename, size, mtime, features_json,
                 category, scan_status, now, now),
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
        category: str | None = None,
        seed: int | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询视频摘要，返回 ``(items, total)``。"""
        conditions: list[str] = []
        params: list[Any] = []
        if category is not None:
            conditions.append("v.category=?")
            params.append(normalize_category(category))
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
            SELECT v.id, v.path, v.filename, v.category, v.size_bytes, v.mtime,
                   v.duration_sec, v.screenshot, v.features, v.present,
                   v.missing_since, v.favorite, v.scan_status, v.created_at, v.updated_at,
                   (SELECT COUNT(*) FROM video_files f
                    WHERE f.video_id=v.id AND f.present=1) AS file_count,
                   m.video_id AS metadata_video_id, m.title, m.original_title, m.year,
                   m.code, m.cover_url, m.cover_local, m.scrape_status, m.source_name,
                   m.source_names, m.last_scraped_at, m.genres, m.tags, m.actresses, m.studio,
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

    def get_video_cover_path(self, video_id: int) -> str | None:
        """只查询封面相对路径，供图片接口使用。

        海报墙一次会请求几十张封面，没必要为此加载完整详情（文件与演员列表）。
        """
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT v.id, m.cover_local FROM videos v "
                "LEFT JOIN metadata m ON m.video_id=v.id WHERE v.id=?",
                (video_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError("视频不存在")
        return row["cover_local"]

    def get_video_screenshot(self, video_id: int) -> str | None:
        """只查询截图相对路径；视频不存在返回 404。"""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT screenshot FROM videos WHERE id=?", (video_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError("视频不存在")
        return row["screenshot"]

    def delete_video(self, video_id: int) -> None:
        """删除视频记录及其本地封面/截图文件；关联元数据由外键级联清理。"""
        with self.db.connection() as conn:
            # 先取文件路径，删除记录后就查不到了。
            row = conn.execute(
                "SELECT v.screenshot, m.cover_local FROM videos v "
                "LEFT JOIN metadata m ON m.video_id = v.id WHERE v.id=?",
                (video_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError("视频不存在")
            conn.execute("DELETE FROM videos WHERE id=?", (video_id,))
        remove_local_images(
            getattr(self, "data_dir", None),
            [row["cover_local"], row["screenshot"]],
        )

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
        image_paths: list[str | None] = []
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
                    # 影片记录即将删除，先记下封面/截图路径以便清理文件。
                    image = conn.execute(
                        "SELECT v.screenshot, m.cover_local FROM videos v "
                        "LEFT JOIN metadata m ON m.video_id = v.id WHERE v.id=?",
                        (video_id,),
                    ).fetchone()
                    if image is not None:
                        image_paths = [image["cover_local"], image["screenshot"]]
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
        if record_deleted:
            remove_local_images(getattr(self, "data_dir", None), image_paths)
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
                "source_names": _json_load(data.pop("source_names", None), []),
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
                "scrape_status", "source_name", "source_names", "last_scraped_at",
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
