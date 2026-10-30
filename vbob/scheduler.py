from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from .jobs import JobManager
from .scans import start_scan
from .store import Store

log = logging.getLogger(__name__)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class ScanScheduler:
    """Periodically starts scans for directories with an interval configured."""

    def __init__(self, store: Store, jobs: JobManager, interval_seconds: int = 30) -> None:
        self.store = store
        self.jobs = jobs
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="scan-scheduler", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self._tick()
            except Exception:  # noqa: BLE001 - scheduler must keep running
                log.exception("scan scheduler tick failed")

    def _tick(self) -> None:
        now = datetime.now(timezone.utc)
        for root in self.store.list_roots(enabled_only=True):
            minutes = int(root.get("scan_interval_minutes") or 0)
            if minutes <= 0 or root.get("active_job"):
                continue
            last = _parse_time(
                root.get("last_scan_started_at") or root.get("last_scan_at")
            )
            if last is not None and (now - last).total_seconds() < minutes * 60:
                continue
            log.info("auto scan root %s (%s)", root["id"], root["path"])
            start_scan(self.store, self.jobs, [root["id"]], root_id=root["id"])
