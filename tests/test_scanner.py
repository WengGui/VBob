from __future__ import annotations

from pathlib import Path

import pytest

from vbob.db import Database
from vbob.errors import ConflictError
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


def test_same_code_files_are_grouped(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    media = tmp_path / "media"
    media.mkdir()
    first = media / "ONSD-489-a.mp4"
    second = media / "ONSD-489-b.mp4"
    first.write_bytes(b"a")
    second.write_bytes(b"bb")
    root = store.create_root(str(media))

    make_scanner(store).run([root["id"]])

    items, total = store.list_videos()
    assert total == 1
    assert items[0]["file_count"] == 2

    # 批量刮削以影片分组为单位，两个文件只会刮削一次。
    assert store.list_video_ids_for_scrape(root["id"], force=True) == [items[0]["id"]]

    detail = store.get_video(items[0]["id"])
    assert len(detail["files"]) == 2
    first_file = next(file for file in detail["files"] if file["filename"] == first.name)

    # 多文件时不指定文件直接播放应要求前端先选择。
    with pytest.raises(ConflictError) as excinfo:
        store.get_video_path(items[0]["id"])
    assert excinfo.value.code == "multiple_files"
    path, filename = store.get_video_path(items[0]["id"], first_file["id"])
    assert filename == first.name
    assert path.endswith(first.name)

    # 删除其中一个文件后，分组仍然存在，文件数降为 1。
    first.unlink()
    summary = make_scanner(store).run([root["id"]])
    assert summary.missing == 1
    detail = store.get_video(items[0]["id"])
    assert detail["video"]["present"] is True
    assert detail["video"]["file_count"] == 1
    assert len(detail["files"]) == 2


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


def test_new_file_attaches_to_existing_group(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    media = tmp_path / "media"
    media.mkdir()
    first = media / "ONSD-489-a.mp4"
    first.write_bytes(b"a")
    root = store.create_root(str(media))

    make_scanner(store).run([root["id"]])
    items, _ = store.list_videos()
    assert len(items) == 1
    video_id = items[0]["id"]

    # 后续新增同番号文件应挂到已有分组，而不是再生成一张海报。
    second = media / "ONSD-489-b.mp4"
    second.write_bytes(b"bb")
    summary = make_scanner(store).run([root["id"]])
    assert summary.added == 1
    items, total = store.list_videos()
    assert total == 1
    assert items[0]["id"] == video_id
    assert items[0]["file_count"] == 2
    detail = store.get_video(video_id)
    assert {file["filename"] for file in detail["files"]} == {first.name, second.name}


def test_delete_selected_files_and_record(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    media = tmp_path / "media"
    media.mkdir()
    first = media / "ONSD-489-a.mp4"
    second = media / "ONSD-489-b.mp4"
    first.write_bytes(b"a")
    second.write_bytes(b"bb")
    root = store.create_root(str(media))
    make_scanner(store).run([root["id"]])

    items, _ = store.list_videos()
    video_id = items[0]["id"]
    files = store.get_video(video_id)["files"]
    first_file = next(file for file in files if file["filename"] == first.name)

    # 只删除其中一个文件：磁盘文件消失，影片记录和另一个文件保留。
    result = store.delete_video_files(video_id, [first_file["id"]])
    assert result["deleted_files"] == 1
    assert result["record_deleted"] is False
    assert result["remaining_files"] == 1
    assert not first.exists()
    assert second.exists()
    detail = store.get_video(video_id)
    assert [file["filename"] for file in detail["files"]] == [second.name]
    assert detail["video"]["file_count"] == 1

    # 删除最后一个文件后，影片记录也会被移除。
    result = store.delete_video_files(video_id, [detail["files"][0]["id"]])
    assert result["deleted_files"] == 1
    assert result["record_deleted"] is True
    assert result["remaining_files"] == 0
    assert not second.exists()
    items, total = store.list_videos()
    assert total == 0


def test_episode_files_group_into_one_video(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    media = tmp_path / "media"
    series = media / "光与影的传说"
    series.mkdir(parents=True)
    for name in ("光与影的传说1.mp4", "光与影的传说2.mp4", "光与影的传说3.mp4"):
        (series / name).write_bytes(b"video")
    root = store.create_root(str(media))

    make_scanner(store).run([root["id"]])

    items, total = store.list_videos()
    assert total == 1
    assert items[0]["file_count"] == 3
    assert items[0]["features"]["title"] == "光与影的传说"
    detail = store.get_video(items[0]["id"])
    assert {file["filename"] for file in detail["files"]} == {
        "光与影的传说1.mp4",
        "光与影的传说2.mp4",
        "光与影的传说3.mp4",
    }
    # 批量刮削按剧集分组只执行一次。
    assert store.list_video_ids_for_scrape(root["id"], force=True) == [items[0]["id"]]
