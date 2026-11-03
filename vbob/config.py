"""默认设置、数据目录解析与配置合并工具。

``DEFAULT_SETTINGS`` 保存完整基线，数据库 settings 表只存覆盖值；
读取时用 ``deep_merge`` 补齐，写入前由 ``vbob.store.validate_settings`` 统一校验。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

APP_NAME = "VBob"

# 设置按分组存库，三个 key 同时也是 update_settings 允许的顶层字段。
DEFAULT_SETTINGS: dict[str, Any] = {
    "scan": {
        "extensions": [
            "mp4", "mkv", "avi", "wmv", "mov", "ts", "m2ts",
            "mpg", "mpeg", "flv", "webm", "rmvb", "m4v",
        ],
        "ignore_globs": [],
        "min_size_mb": 50,
        "follow_symlinks": False,
    },
    "scraping": {
        "clean_rules": [],
        "workers": 3,
        "cache_ttl_sec": 600,
        "negative_ttl_sec": 60,
    },
    "playback": {
        "player": None,
    },
}


def default_data_dir() -> Path:
    """返回默认数据目录。

    - 开发运行：``<当前工作目录>/data``；
    - PyInstaller 打包：``<exe 所在目录>/data``，保证拷贝整个程序文件夹即可迁移；
    - ``VBOB_DATA_DIR`` / ``--data-dir`` 始终优先。
    """
    env = os.environ.get("VBOB_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return (Path(sys.executable).resolve().parent / "data").resolve()
    return (Path.cwd() / "data").resolve()


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """递归合并 ``patch`` 到 ``base``，返回新字典且不修改入参。"""
    merged: dict[str, Any] = dict(base)
    for key, value in patch.items():
        # 两边都是对象时继续下钻；数组、标量和 null 直接覆盖。
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
