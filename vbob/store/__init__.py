"""数据访问层。

Store 按领域拆成多个 mixin（settings/roots/sources/videos/metadata/actresses/jobs），
这里组合成单一 ``Store`` 门面，保持原有调用方式不变。
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..db import Database
from .actresses import ActressMixin
from .helpers import SORT_ORDERS, validate_settings
from .jobs import JobMixin
from .maintenance import MaintenanceMixin
from .metadata import MetadataMixin
from .roots import RootMixin
from .settings import SettingsMixin
from .sources import SourceMixin
from .videos import VideoMixin

log = logging.getLogger(__name__)

__all__ = ["Store", "SORT_ORDERS", "validate_settings"]


class Store(
    SettingsMixin,
    RootMixin,
    SourceMixin,
    VideoMixin,
    MetadataMixin,
    ActressMixin,
    JobMixin,
    MaintenanceMixin,
):
    """应用的全部数据库读写入口，按领域由多个 mixin 组合而成。"""

    def __init__(self, db: Database, data_dir: Path | None = None) -> None:
        """绑定数据库封装；``data_dir`` 用于清理封面等本地文件。"""
        self.db = db
        self.data_dir = data_dir
