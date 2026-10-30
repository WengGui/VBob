from __future__ import annotations

from typing import Any

from .extractors import FeaturePipeline
from .jobs import JobManager
from .scanner import Scanner, ScanOptions
from .store import Store


def run_scan(
    store: Store,
    root_ids: list[int],
    full: bool,
    job_id: str,
    cancel_event: Any,
    progress: Any,
) -> None:
    settings = store.get_settings()
    options = ScanOptions.from_settings(settings)
    pipeline = FeaturePipeline(settings["scraping"]["clean_rules"])
    scanner = Scanner(
        store,
        options,
        pipeline=pipeline,
        cancel_event=cancel_event,
        progress=progress,
    )
    summary = scanner.run(root_ids, full=full)
    message = (
        f"完成：新增 {summary.added}，更新 {summary.updated}，"
        f"未变 {summary.unchanged}，失败 {summary.failed}"
    )
    if summary.errors:
        message += f"；首个错误：{summary.errors[0]}"
    progress(
        done=summary.total,
        total=summary.total,
        failed=summary.failed,
        message=message,
    )


def start_scan(
    store: Store,
    jobs: JobManager,
    root_ids: list[int],
    *,
    full: bool = False,
    root_id: int | None = None,
) -> str:
    def target(job_id: str, cancel_event: Any, progress: Any) -> None:
        run_scan(store, root_ids, full, job_id, cancel_event, progress)

    return jobs.start(
        "scan",
        {"root_ids": root_ids, "full": full},
        target,
        root_id=root_id,
    )
