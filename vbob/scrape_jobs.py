from __future__ import annotations

from pathlib import Path
from typing import Any

from .jobs import JobManager
from .scraper import Scraper
from .store import Store


def start_video_scrape(
    store: Store,
    jobs: JobManager,
    data_dir: Path,
    video_id: int,
    *,
    force: bool = True,
    overwrite_manual: bool = False,
) -> str:
    detail = store.get_video(video_id)
    root_id = detail["video"].get("root_id")

    def target(job_id: str, cancel_event: Any, progress: Any) -> None:
        scraper = Scraper(store, data_dir, job_id)
        outcome = scraper.scrape_video(
            video_id, force=force, overwrite_manual=overwrite_manual
        )
        progress(
            done=1,
            total=1,
            failed=1 if outcome.get("status") == "failed" else 0,
            message=outcome.get("message") or f"刮削结果: {outcome.get('status')}",
        )

    return jobs.start(
        "scrape_one",
        {"video_id": video_id, "force": force, "overwrite_manual": overwrite_manual},
        target,
        root_id=root_id,
    )


def start_actress_scrape(
    store: Store,
    jobs: JobManager,
    data_dir: Path,
    actress_id: int,
    *,
    force: bool = True,
    overwrite_manual: bool = False,
) -> str:
    store.get_actress(actress_id)

    def target(job_id: str, cancel_event: Any, progress: Any) -> None:
        scraper = Scraper(store, data_dir, job_id)
        outcome = scraper.scrape_actress(
            actress_id, force=force, overwrite_manual=overwrite_manual
        )
        progress(
            done=1,
            total=1,
            failed=1 if outcome.get("status") == "failed" else 0,
            message=outcome.get("message") or f"演员刮削结果: {outcome.get('status')}",
        )

    return jobs.start(
        "scrape_actress",
        {"actress_id": actress_id, "force": force, "overwrite_manual": overwrite_manual},
        target,
    )


def start_root_scrape(
    store: Store,
    jobs: JobManager,
    data_dir: Path,
    root_id: int,
    *,
    force: bool = False,
    overwrite_manual: bool = False,
) -> str:
    store.get_root(root_id)

    def target(job_id: str, cancel_event: Any, progress: Any) -> None:
        scraper = Scraper(store, data_dir, job_id)
        counts = scraper.scrape_root(
            root_id,
            force=force,
            overwrite_manual=overwrite_manual,
            cancel_event=cancel_event,
            progress=progress,
        )
        progress(
            message=(
                f"完成：成功 {counts['success']}，无匹配 {counts['no_match']}，"
                f"失败 {counts['failed']}，跳过 {counts['skipped']}"
            ),
            failed=counts["failed"],
        )

    return jobs.start(
        "scrape_batch",
        {"root_id": root_id, "force": force, "overwrite_manual": overwrite_manual},
        target,
        root_id=root_id,
    )
