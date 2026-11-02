"""目录扫描器：遍历根目录、增量比对缓存、提取特征并写入视频表。

关键流程：
1. _collect 预先收集所有符合条件的视频文件（扩展名/忽略规则/最小体积/符号链接）；
2. run 先发现再处理，用扫描缓存按 (size, mtime) 判断文件是否未变；
3. 未变文件沿用缓存记录，新增或变更文件重新提取特征并 upsert；
4. 本轮未出现的记录标记为 missing。

支持通过 cancel_event 中途取消，并为每个根目录记录扫描状态。
"""

from __future__ import annotations

import fnmatch
import logging
import os
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .errors import JobCanceled
from .extractors import FeaturePipeline, FileRef
from .paths import canonical_path, path_key
from .store import Store

log = logging.getLogger(__name__)

# 系统/回收站/群晖缩略图等目录，遍历时直接跳过。
IGNORED_DIRS = {
    "$recycle.bin",
    "system volume information",
    "@eadir",
    "#recycle",
    "lost+found",
}


@dataclass(frozen=True)
class ScanOptions:
    """扫描参数，由全局设置中的 scan 段转换而来。"""

    extensions: frozenset[str]
    ignore_globs: tuple[str, ...] = ()
    min_size_mb: int = 50
    follow_symlinks: bool = False

    @classmethod
    def from_settings(cls, settings: dict) -> "ScanOptions":
        """从全局设置构造扫描参数。"""
        scan = settings["scan"]
        return cls(
            extensions=frozenset(scan["extensions"]),
            ignore_globs=tuple(scan["ignore_globs"]),
            min_size_mb=int(scan["min_size_mb"]),
            follow_symlinks=bool(scan["follow_symlinks"]),
        )


@dataclass
class ScanEntry:
    """一个待入库的视频文件；key 是跨平台规范化的路径标识。"""

    path: str
    key: str
    rel_path: str
    filename: str
    dirs: tuple[str, ...]
    size: int
    mtime: int


@dataclass
class ScanSummary:
    """一次扫描的计数汇总与错误列表。"""

    total: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    missing: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        """最多保留 50 条错误，避免大批量失败时占满内存/响应体。"""
        if len(self.errors) < 50:
            self.errors.append(message)


ProgressCallback = Callable[..., None]


class Scanner:
    """扫描一个或多个根目录，并把结果写入 Store。"""

    def __init__(
        self,
        store: Store,
        options: ScanOptions,
        *,
        pipeline: FeaturePipeline | None = None,
        cancel_event=None,
        progress: ProgressCallback | None = None,
    ) -> None:
        self.store = store
        self.options = options
        self.pipeline = pipeline or FeaturePipeline()
        self.cancel_event = cancel_event
        self.progress = progress or (lambda **_: None)
        self.summary = ScanSummary()
        self._min_bytes = options.min_size_mb * 1024 * 1024
        self._last_progress = 0.0  # 上次进度回调时间，用于节流

    def _cancelled(self) -> bool:
        """取消标记是否已置位。"""
        return self.cancel_event is not None and self.cancel_event.is_set()

    def run(self, root_ids: list[int], *, full: bool = False) -> ScanSummary:
        """执行扫描；full=True 时忽略缓存，强制重新提取所有文件。"""
        roots = [self.store.get_root(root_id) for root_id in root_ids]
        collected: list[tuple[dict, list[ScanEntry]]] = []

        self.progress(message="正在发现文件…")
        for root in roots:
            self._check_cancel()
            # 先完整发现文件，便于给进度条一个准确的总数。
            entries = self._collect(root)
            collected.append((root, entries))
            self.summary.total += len(entries)

        total = self.summary.total
        done = 0
        self.progress(done=0, total=total, message="正在扫描…")

        for root, entries in collected:
            self._check_cancel()
            started = time.monotonic()
            self.store.start_root_scan(root["id"])
            try:
                cache = self.store.load_scan_cache(root["id"])
                # seen 记录本轮出现的文件 ID，结束后用于把未出现的文件标记为 missing。
                seen: set[int] = set()
                for entry in entries:
                    self._check_cancel()
                    done += 1
                    existing = cache.get(entry.key)
                    # 增量判断：大小与 mtime 都一致才视为未变，直接复用缓存。
                    if (
                        existing
                        and not full
                        and existing["size_bytes"] == entry.size
                        and existing["mtime"] == entry.mtime
                    ):
                        seen.add(int(existing["id"]))
                        # 文件重新出现时恢复可见状态。
                        if not existing["present"]:
                            self.store.mark_seen(int(existing["id"]))
                        self.summary.unchanged += 1
                    else:
                        # 仅对新增/变更文件做特征提取，降低扫描开销。
                        features: dict[str, object] = {}
                        scan_status = "scanned"
                        try:
                            features = self.pipeline.extract(
                                FileRef(
                                    filename=entry.filename,
                                    rel_path=entry.rel_path,
                                    dirs=entry.dirs,
                                )
                            )
                        except Exception as exc:  # noqa: BLE001
                            scan_status = "error"
                            self.summary.failed += 1
                            self.summary.add_error(f"{entry.path}: {exc}")
                        try:
                            _, file_id, _ = self.store.upsert_video_file(
                                root_id=root["id"],
                                path=entry.path,
                                key=entry.key,
                                filename=entry.filename,
                                size=entry.size,
                                mtime=entry.mtime,
                                features=features,
                                scan_status=scan_status,
                            )
                        except Exception as exc:  # noqa: BLE001
                            self.summary.failed += 1
                            self.summary.add_error(f"{entry.path}: {exc}")
                            log.exception("failed to store %s", entry.path)
                            continue
                        seen.add(file_id)
                        if existing:
                            self.summary.updated += 1
                        else:
                            self.summary.added += 1
                    self._tick(done, total)

                # 本轮未出现的旧记录统一标记为 missing。
                self.summary.missing += self.store.mark_missing(root["id"], seen)
            except JobCanceled:
                self.store.finish_root_scan(
                    root["id"], "canceled", int((time.monotonic() - started) * 1000)
                )
                raise
            except BaseException:
                self.store.finish_root_scan(
                    root["id"], "failed", int((time.monotonic() - started) * 1000)
                )
                raise
            else:
                self.store.finish_root_scan(
                    root["id"], "succeeded", int((time.monotonic() - started) * 1000)
                )

        self._tick(done, total, force=True)
        return self.summary

    def _check_cancel(self) -> None:
        """取消标记置位时抛出 JobCanceled。"""
        if self._cancelled():
            raise JobCanceled()

    def _tick(self, done: int, total: int, *, force: bool = False) -> None:
        """按 0.4 秒节流上报进度；处理完成时强制上报。"""
        now = time.monotonic()
        if force or done == total or now - self._last_progress >= 0.4:
            self._last_progress = now
            self.progress(
                done=done,
                total=total,
                failed=self.summary.failed,
                message=f"已扫描 {done}/{total} 个文件",
            )

    def _collect(self, root: dict) -> list[ScanEntry]:
        """遍历根目录并收集符合扫描条件的文件条目。"""
        root_path = Path(root["path"])
        entries: list[ScanEntry] = []
        if not root_path.is_dir():
            self.summary.failed += 1
            self.summary.add_error(f"扫描目录不可访问: {root_path}")
            return entries

        def on_error(exc: OSError) -> None:
            self.summary.failed += 1
            self.summary.add_error(f"{exc.filename or root_path}: {exc}")
            log.warning("scan error: %s", exc)

        for dirpath, dirnames, filenames in os.walk(
            root_path, followlinks=self.options.follow_symlinks, onerror=on_error
        ):
            self._check_cancel()
            # 原地过滤子目录，os.walk 后续就不会进入这些目录。
            dirnames[:] = [
                name
                for name in dirnames
                if name.lower() not in IGNORED_DIRS and not name.startswith(".")
            ]
            for name in filenames:
                self._check_cancel()
                if name.startswith(".") or name.lower() in IGNORED_DIRS:
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, root_path)
                if self._ignored(rel, name):
                    continue
                ext = os.path.splitext(name)[1].lower().lstrip(".")
                if ext not in self.options.extensions:
                    continue
                try:
                    st = os.stat(full, follow_symlinks=self.options.follow_symlinks)
                except OSError as exc:
                    self.summary.failed += 1
                    self.summary.add_error(f"{full}: {exc}")
                    continue
                # 未开启 follow_symlinks 时显式排除符号链接。
                if not self.options.follow_symlinks and stat.S_ISLNK(st.st_mode):
                    continue
                if not stat.S_ISREG(st.st_mode):
                    continue
                if st.st_size < self._min_bytes:
                    continue
                parent = os.path.dirname(rel)
                # 父目录从近到远存放，供特征提取优先使用最近的目录名。
                dirs = tuple(reversed(parent.split(os.sep))) if parent else ()
                entries.append(
                    ScanEntry(
                        path=canonical_path(full),
                        key=path_key(full),
                        rel_path=rel,
                        filename=name,
                        dirs=dirs,
                        size=int(st.st_size),
                        mtime=int(st.st_mtime),
                    )
                )
        return entries

    def _ignored(self, rel_path: str, name: str) -> bool:
        """按 fnmatch 匹配相对路径或文件名（大小写不敏感）。"""
        if not self.options.ignore_globs:
            return False
        rel = rel_path.replace(os.sep, "/").casefold()
        base = name.casefold()
        for pattern in self.options.ignore_globs:
            folded = pattern.casefold()
            if fnmatch.fnmatchcase(rel, folded) or fnmatch.fnmatchcase(base, folded):
                return True
        return False
