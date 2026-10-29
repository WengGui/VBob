from __future__ import annotations

import os
import sys
from pathlib import Path


def canonical_path(path: str | Path) -> str:
    """Absolute, normalized path used for display."""
    return os.path.normpath(os.path.abspath(os.path.expanduser(str(path))))


def path_key(path: str | Path) -> str:
    """Comparison key for deduplication.

    Windows and macOS treat paths case-insensitively, so the key is folded
    there; Linux keeps the original case.
    """
    key = os.path.normcase(os.path.normpath(os.path.abspath(os.path.expanduser(str(path)))))
    if sys.platform == "darwin":
        key = key.casefold()
    return key


def is_within(child_key: str, parent_key: str) -> bool:
    """True when a folded path key is equal to or below a parent key."""
    child = child_key.rstrip(os.sep)
    parent = parent_key.rstrip(os.sep)
    return child == parent or child.startswith(parent + os.sep)
