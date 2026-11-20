"""数据目录维护：清理数据库已不再引用的封面与截图。"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


class MaintenanceMixin:
    """启动时清理孤儿图片，修复历史版本删除记录后遗留的文件。"""

    def cleanup_unused_images(self) -> int:
        """删除 ``covers/`` 与 ``screenshots/`` 下没有被任何记录引用的文件。

        返回删除数量。删除操作是幂等的：异常、权限不足或被占用时只记日志，
        不影响服务启动。
        """
        data_dir = getattr(self, "data_dir", None)
        if data_dir is None:
            return 0
        base = Path(data_dir).resolve()
        referenced = self._referenced_images()
        removed = 0
        for folder in ("covers", "screenshots"):
            root = base / folder
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                relative = path.relative_to(base).as_posix()
                if relative in referenced:
                    continue
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    log.warning("failed to remove unused image %s", path, exc_info=True)
        if removed:
            log.info("removed %d unused image(s)", removed)
        return removed

    def _referenced_images(self) -> set[str]:
        """收集数据库中仍被引用的图片相对路径（统一用 / 分隔）。"""
        referenced: set[str] = set()
        with self.db.connection() as conn:
            queries = (
                "SELECT cover_local AS path FROM metadata WHERE cover_local IS NOT NULL",
                "SELECT cover_local AS path FROM actresses WHERE cover_local IS NOT NULL",
                "SELECT screenshot AS path FROM videos WHERE screenshot IS NOT NULL",
            )
            for sql in queries:
                for row in conn.execute(sql):
                    value = row["path"]
                    if value:
                        referenced.add(Path(str(value)).as_posix())
        return referenced
