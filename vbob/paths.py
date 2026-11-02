"""路径规范化、去重键与父子目录判断工具。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def canonical_path(path: str | Path) -> str:
    """返回用于展示的绝对、规范化路径。"""
    # 只做展开和规范化，不解析符号链接，保留用户实际配置的路径形态。
    return os.path.normpath(os.path.abspath(os.path.expanduser(str(path))))


def path_key(path: str | Path) -> str:
    """返回用于去重比较的路径键。

    Windows 与 macOS 的文件系统通常忽略大小写，因此在这两类系统上折叠大小写；
    Linux 保留原始大小写，避免把不同文件误判为重复。
    """
    key = os.path.normcase(os.path.normpath(os.path.abspath(os.path.expanduser(str(path)))))
    if sys.platform == "darwin":
        # macOS 的 normcase 是空操作，需要额外 casefold 才能忽略大小写。
        key = key.casefold()
    return key


def is_within(child_key: str, parent_key: str) -> bool:
    """判断折叠后的路径键是否等于父路径或位于父路径之下。"""
    child = child_key.rstrip(os.sep)
    parent = parent_key.rstrip(os.sep)
    # 补上分隔符再比较前缀，避免 /a/bc 被误认为 /a/b 的子目录。
    return child == parent or child.startswith(parent + os.sep)
