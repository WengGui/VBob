from __future__ import annotations

from pathlib import Path

from vbob.db import Database
from vbob.scanner import Scanner, ScanOptions
from vbob.store import Store


def make_store(tmp_path: Path) -> Store:
    db = Database(tmp_path / "vbob.db")
    db.migrate()
    return Store(db)


def make_scanner(store: Store) -> Scanner:
    options = ScanOptions(extensions=frozenset({"mp4", "mkv", "avi"}), min_size_mb=0)
    return Scanner(store, options)


def test_scan_incremental_and_missing(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    media = tmp_path / "media"
    media.mkdir()
    first = media / "SSIS-001.mp4"
    second = media / "Movie.2023.mkv"
    first.write_bytes(b"a")
    second.write_bytes(b"bb")
    root = store.create_root(str(media))

    summary = make_scanner(store).run([root["id"]])
    assert summary.total == 2
    assert summary.added == 2
    assert summary.missing == 0

    items, total = store.list_videos()
    assert total == 2
    codes = {item["features"].get("jav_code") for item in items}
    assert "SSIS-001" in codes

    summary = make_scanner(store).run([root["id"]])
    assert summary.unchanged == 2
    assert summary.added == 0
    assert summary.updated == 0

    first.write_bytes(b"changed")
    summary = make_scanner(store).run([root["id"]])
    assert summary.updated == 1
    assert summary.unchanged == 1

    first.unlink()
    summary = make_scanner(store).run([root["id"]])
    assert summary.missing == 1
    items, total = store.list_videos(present=False)
    assert total == 1
    assert items[0]["filename"] == "SSIS-001.mp4"

    # A reappearing file is marked present again.
    first.write_bytes(b"a")
    summary = make_scanner(store).run([root["id"]])
    assert summary.updated == 1
    assert summary.unchanged == 1
    _, total = store.list_videos(present=True)
    assert total == 2


def test_ignored_files(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    media = tmp_path / "media"
    media.mkdir()
    (media / "keep.mp4").write_bytes(b"a")
    (media / "sample.mp4").write_bytes(b"a")
    (media / ".hidden.mp4").write_bytes(b"a")
    (media / "note.txt").write_bytes(b"a")
    root = store.create_root(str(media))

    options = ScanOptions(
        extensions=frozenset({"mp4"}), ignore_globs=("*sample*",), min_size_mb=0
    )
    summary = Scanner(store, options).run([root["id"]])
    assert summary.total == 1
    items, total = store.list_videos()
    assert total == 1
    assert items[0]["filename"] == "keep.mp4"
