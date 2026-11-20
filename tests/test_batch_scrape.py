"""批量刮削的并发执行与失败隔离。"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from vbob.db import Database
from vbob.scraper import Scraper
from vbob.store import Store


@pytest.fixture
def scraper(tmp_path: Path) -> Scraper:
    db = Database(tmp_path / "vbob.db")
    db.migrate()
    store = Store(db, tmp_path)
    return Scraper(store, tmp_path, "job-test")


def test_batch_scrape_runs_concurrently_and_counts(
    scraper: Scraper, monkeypatch
) -> None:
    scraper.store.update_settings({"scraping": {"workers": 3}})
    monkeypatch.setattr(
        scraper.store, "list_video_ids_for_scrape", lambda *args, **kwargs: [1, 2, 3, 4, 5]
    )

    lock = threading.Lock()
    active = 0
    peak = 0

    def fake_scrape(video_id: int, **kwargs) -> dict:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return {"status": "success"}

    monkeypatch.setattr(scraper, "scrape_video", fake_scrape)
    progress: list[dict] = []

    counts = scraper.scrape_root(1, progress=lambda **kwargs: progress.append(kwargs))

    assert counts["success"] == 5
    assert peak >= 2  # 确实并发执行
    assert progress[-1]["done"] == 5
    assert progress[-1]["total"] == 5


def test_batch_scrape_isolates_failures(scraper: Scraper, monkeypatch) -> None:
    scraper.store.update_settings({"scraping": {"workers": 2}})
    monkeypatch.setattr(
        scraper.store, "list_video_ids_for_scrape", lambda *args, **kwargs: [1, 2, 3]
    )

    def fake_scrape(video_id: int, **kwargs) -> dict:
        if video_id == 2:
            raise RuntimeError("boom")
        return {"status": "success"}

    monkeypatch.setattr(scraper, "scrape_video", fake_scrape)
    counts = scraper.scrape_root(1)

    assert counts["success"] == 2
    assert counts["failed"] == 1
    assert counts["errors"] == 1


def test_batch_scrape_cancel_stops_remaining(scraper: Scraper, monkeypatch) -> None:
    scraper.store.update_settings({"scraping": {"workers": 1}})
    monkeypatch.setattr(
        scraper.store, "list_video_ids_for_scrape", lambda *args, **kwargs: [1, 2, 3]
    )
    event = threading.Event()
    calls: list[int] = []

    def fake_scrape(video_id: int, **kwargs) -> dict:
        calls.append(video_id)
        event.set()
        return {"status": "success"}

    monkeypatch.setattr(scraper, "scrape_video", fake_scrape)

    from vbob.errors import JobCanceled

    with pytest.raises(JobCanceled):
        scraper.scrape_root(1, cancel_event=event)
    assert calls == [1]
