"""扫描调度器：后台线程按固定周期检查根目录的自动扫描间隔。

每个 tick 遍历启用的根目录，跳过未配置间隔或已有任务运行的根目录，
根据上次扫描时间判断是否到期，到期则提交一次扫描任务。
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from .jobs import JobManager
from .scans import start_scan
from .store import Store

log = logging.getLogger(__name__)


def _parse_time(value: str | None) -> datetime | None:
    """解析 ISO 时间字符串（兼容结尾 Z）；非法值返回 None。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class ScanScheduler:
    """周期性为配置了扫描间隔的目录启动扫描。"""

    def __init__(self, store: Store, jobs: JobManager, interval_seconds: int = 30) -> None:
        self.store = store
        self.jobs = jobs
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """启动守护线程；重复调用不会创建第二个线程。"""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="scan-scheduler", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """请求停止；线程会在下一次等待超时后退出。"""
        self._stop.set()

    def _loop(self) -> None:
        """以 interval_seconds 为周期运行；单次异常只记日志，保持调度器存活。"""
        while not self._stop.wait(self.interval_seconds):
            try:
                self._tick()
            except Exception:  # noqa: BLE001 - scheduler must keep running
                log.exception("scan scheduler tick failed")

    def _tick(self) -> None:
        """检查各根目录是否到达扫描时间，到期则提交扫描任务。"""
        now = datetime.now(timezone.utc)
        for root in self.store.list_roots(enabled_only=True):
            minutes = int(root.get("scan_interval_minutes") or 0)
            # 间隔 <=0 表示不自动扫描；已有任务时跳过，避免重叠。
            if minutes <= 0 or root.get("active_job"):
                continue
            # 优先用“上次开始时间”，避免长时间扫描期间被重复触发。
            last = _parse_time(
                root.get("last_scan_started_at") or root.get("last_scan_at")
            )
            if last is not None and (now - last).total_seconds() < minutes * 60:
                continue
            log.info("auto scan root %s (%s)", root["id"], root["path"])
            start_scan(self.store, self.jobs, [root["id"]], root_id=root["id"])
