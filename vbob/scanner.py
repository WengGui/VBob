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

IGNORED_DIRS = {
    "$recycle.bin",
    "system volume information",
    "@eadir",
    "#recycle",
    "lost+found",
}


@dataclass(frozen=True)
class ScanOptions:
    extensions: frozenset[str]
    ignore_globs: tuple[str, ...] = ()
    min_size_mb: int = 50
    follow_symlinks: bool = False

    @classmethod
    def from_settings(cls, settings: dict) -> "ScanOptions":
        scan = settings["scan"]
        return cls(
            extensions=frozenset(scan["extensions"]),
            ignore_globs=tuple(scan["ignore_globs"]),
            min_size_mb=int(scan["min_size_mb"]),
            follow_symlinks=bool(scan["follow_symlinks"]),
        )


@dataclass
class ScanEntry:
    path: str
    key: str
    rel_path: str
    filename: str
    dirs: tuple[str, ...]
    size: int
    mtime: int


@dataclass
class ScanSummary:
    total: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    missing: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        if len(self.errors) < 50:
            self.errors.append(message)


ProgressCallback = Callable[..., None]


class Scanner:
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
        self._last_progress = 0.0

    def _cancelled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()

    def run(self, root_ids: list[int], *, full: bool = False) -> ScanSummary:
        roots = [self.store.get_root(root_id) for root_id in root_ids]
        collected: list[tuple[dict, list[ScanEntry]]] = []

        self.progress(message="正在发现文件…")
        for root in roots:
            self._check_cancel()
            entries = self._collect(root)
            collected.append((root, entries))
            self.summary.total += len(entries)

        total = self.summary.total
        done = 0
        self.progress(done=0, total=total, message="正在扫描…")

        for root, entries in collected:
            self._check_cancel()
            cache = self.store.load_scan_cache(root["id"])
            seen: set[int] = set()
            for entry in entries:
                self._check_cancel()
                done += 1
                existing = cache.get(entry.key)
                if (
                    existing
                    and not full
                    and existing["size_bytes"] == entry.size
                    and existing["mtime"] == entry.mtime
                ):
                    seen.add(int(existing["id"]))
                    if not existing["present"]:
                        self.store.mark_seen(int(existing["id"]))
                    self.summary.unchanged += 1
                else:
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
                    except Exception as exc:  # noqa: BLE001 - one bad file must not abort a scan
                        scan_status = "error"
                        self.summary.failed += 1
                        self.summary.add_error(f"{entry.path}: {exc}")
                    try:
                        video_id = self.store.upsert_video(
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
                    seen.add(video_id)
                    if existing:
                        self.summary.updated += 1
                    else:
                        self.summary.added += 1
                self._tick(done, total)

            self.summary.missing += self.store.mark_missing(root["id"], seen)
            self.store.touch_root_scanned(root["id"])

        self._tick(done, total, force=True)
        return self.summary

    def _check_cancel(self) -> None:
        if self._cancelled():
            raise JobCanceled()

    def _tick(self, done: int, total: int, *, force: bool = False) -> None:
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
                if not self.options.follow_symlinks and stat.S_ISLNK(st.st_mode):
                    continue
                if not stat.S_ISREG(st.st_mode):
                    continue
                if st.st_size < self._min_bytes:
                    continue
                parent = os.path.dirname(rel)
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
        if not self.options.ignore_globs:
            return False
        rel = rel_path.replace(os.sep, "/").casefold()
        base = name.casefold()
        for pattern in self.options.ignore_globs:
            folded = pattern.casefold()
            if fnmatch.fnmatchcase(rel, folded) or fnmatch.fnmatchcase(base, folded):
                return True
        return False
