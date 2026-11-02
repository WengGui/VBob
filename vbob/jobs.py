"""后台任务调度。

每个任务在独立的守护线程中执行，状态和进度写入 SQLite 的 jobs 表，
进程内再保存取消事件，供 worker 在执行过程中轮询。
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Callable

from .db import utc_now
from .errors import JobCanceled
from .store import Store

log = logging.getLogger(__name__)

# 任务函数签名：(job_id, 取消事件, 进度回调)。
JobTarget = Callable[[str, threading.Event, Callable[..., None]], None]


class JobManager:
    """在守护线程中运行任务，并把任务状态同步到 SQLite。"""

    def __init__(self, store: Store) -> None:
        """绑定 Store 并初始化进程内取消事件表。"""
        self.store = store
        self._cancels: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def start(
        self,
        job_type: str,
        payload: dict[str, Any],
        target: JobTarget,
        root_id: int | None = None,
    ) -> str:
        """创建任务记录并启动后台线程，返回任务 ID。"""
        job_id = uuid.uuid4().hex
        self.store.create_job(job_id, job_type, payload, root_id=root_id)
        event = threading.Event()
        # 先登记取消事件再启动线程，避免取消请求早于线程启动时丢失。
        with self._lock:
            self._cancels[job_id] = event
        thread = threading.Thread(
            target=self._run,
            args=(job_id, event, target),
            name=f"job-{job_type}-{job_id[:8]}",
            daemon=True,
        )
        thread.start()
        return job_id

    def cancel(self, job_id: str) -> dict[str, Any]:
        """请求取消任务；已结束的任务直接返回当前状态。"""
        job = self.store.get_job(job_id)
        if job["status"] in {"succeeded", "failed", "canceled"}:
            return job
        # 同时写数据库标记和进程内事件：前者持久化取消意图，后者唤醒当前进程的 worker。
        self.store.request_cancel(job_id)
        with self._lock:
            event = self._cancels.get(job_id)
        if event is not None:
            event.set()
        return self.store.get_job(job_id)

    def recover(self) -> None:
        """启动时把上次进程遗留的 queued/running 任务标记为失败。"""
        count = self.store.recover_orphan_jobs()
        if count:
            log.warning("marked %d interrupted job(s) as failed", count)

    def _run(self, job_id: str, event: threading.Event, target: JobTarget) -> None:
        """线程入口：统一处理任务成功、取消和异常落库。"""
        self.store.update_job(job_id, status="running", started_at=utc_now())
        progress = self._make_progress(job_id)
        try:
            target(job_id, event, progress)
        except JobCanceled:
            self.store.update_job(
                job_id, status="canceled", message="任务已取消", finished_at=utc_now()
            )
        except Exception as exc:  # noqa: BLE001 - never let a worker die silently
            log.exception("job %s failed", job_id)
            self.store.update_job(
                job_id,
                status="failed",
                message=f"{type(exc).__name__}: {exc}",
                finished_at=utc_now(),
            )
        else:
            # 有些任务会正常返回而不抛 JobCanceled，需再按取消事件补记状态。
            if event.is_set():
                self.store.update_job(
                    job_id, status="canceled", message="任务已取消", finished_at=utc_now()
                )
            else:
                self.store.update_job(job_id, status="succeeded", finished_at=utc_now())
        finally:
            with self._lock:
                self._cancels.pop(job_id, None)

    def _make_progress(self, job_id: str) -> Callable[..., None]:
        """包装进度回调，确保写进度失败不会中断任务本身。"""

        def progress(**fields: Any) -> None:
            """任务函数用来上报进度的回调。"""
            try:
                self.store.update_job(job_id, **fields)
            except Exception:  # noqa: BLE001 - progress must not kill the job
                log.exception("failed to update progress for job %s", job_id)

        return progress
