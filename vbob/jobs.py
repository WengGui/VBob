from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Callable

from .db import utc_now
from .errors import JobCanceled
from .store import Store

log = logging.getLogger(__name__)

JobTarget = Callable[[str, threading.Event, Callable[..., None]], None]


class JobManager:
    """Runs jobs in daemon threads and mirrors their state to SQLite."""

    def __init__(self, store: Store) -> None:
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
        job_id = uuid.uuid4().hex
        self.store.create_job(job_id, job_type, payload, root_id=root_id)
        event = threading.Event()
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
        job = self.store.get_job(job_id)
        if job["status"] in {"succeeded", "failed", "canceled"}:
            return job
        self.store.request_cancel(job_id)
        with self._lock:
            event = self._cancels.get(job_id)
        if event is not None:
            event.set()
        return self.store.get_job(job_id)

    def recover(self) -> None:
        count = self.store.recover_orphan_jobs()
        if count:
            log.warning("marked %d interrupted job(s) as failed", count)

    def _run(self, job_id: str, event: threading.Event, target: JobTarget) -> None:
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
        def progress(**fields: Any) -> None:
            try:
                self.store.update_job(job_id, **fields)
            except Exception:  # noqa: BLE001 - progress must not kill the job
                log.exception("failed to update progress for job %s", job_id)

        return progress
