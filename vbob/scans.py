"""扫描任务入口：把 Scanner 包装成 JobManager 的后台任务。

run_scan 从设置读取扫描参数与清洗规则，构造 Scanner 执行扫描，
最后用摘要更新进度；start_scan 只负责提交任务。
"""

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
    """同步执行一次扫描，并上报最终统计。"""
    settings = store.get_settings()
    options = ScanOptions.from_settings(settings)
    # 用户自定义清洗规则会与默认规则合并后用于特征提取。
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
    """创建扫描后台任务；root_id 仅用于任务按根目录筛选。"""
    def target(job_id: str, cancel_event: Any, progress: Any) -> None:
        run_scan(store, root_ids, full, job_id, cancel_event, progress)

    return jobs.start(
        "scan",
        {"root_ids": root_ids, "full": full},
        target,
        root_id=root_id,
    )
