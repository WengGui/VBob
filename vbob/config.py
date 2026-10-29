from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

APP_NAME = "VBob"

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
    env = os.environ.get("VBOB_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "vbob"


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict with ``patch`` recursively merged into ``base``."""
    merged: dict[str, Any] = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
