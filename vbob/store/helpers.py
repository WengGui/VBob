"""Store 使用的常量、JSON/空值处理与设置校验。"""

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
from ..extractors import FeaturePipeline, FileRef
from ..errors import ConflictError, InvalidError, NotFoundError
from ..names import actress_name_key
from ..paths import canonical_path, is_within, path_key
from ..source_config import validate_source_config

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


def remove_local_images(
    data_dir: Path | None, relative_paths: Iterable[str | None]
) -> None:
    """删除数据目录内的封面/截图文件；越界路径和不存在文件都静默忽略。

    记录被删除后调用，避免 covers/ 与 screenshots/ 里堆积孤儿文件。
    路径来自数据库，仍按数据目录做一次越界校验，防止异常值删到目录外。
    """
    if data_dir is None:
        return
    base = data_dir.resolve()
    for relative in relative_paths:
        if not relative:
            continue
        candidate = (base / str(relative)).resolve()
        try:
            candidate.relative_to(base)
        except ValueError:
            log.warning("skip image outside data dir: %s", relative)
            continue
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            log.warning("failed to remove image %s", candidate, exc_info=True)


def _is_blank_value(value: Any) -> bool:
    """判断字段是否为空，用于允许刮削补全“手动标记但没填内容”的字段。"""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip() or value.strip() in {"[]", "{}"}
    if isinstance(value, (list, dict)):
        return not value
    return False


def _metadata_dict(row: Any) -> dict[str, Any] | None:
    """把 metadata 行转成 API 结构，展开 JSON 列并转换完整度标志。"""
    if row is None:
        return None
    data = _row_dict(row)
    data["genres"] = _json_load(data.get("genres"), [])
    data["tags"] = _json_load(data.get("tags"), [])
    data["actresses"] = _json_load(data.get("actresses"), [])
    data["manual_fields"] = _json_load(data.get("manual_fields"), [])
    # 本次成功贡献数据的源列表；source_name 仍保留为首个源，兼容旧逻辑。
    data["source_names"] = _json_load(data.get("source_names"), [])
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
