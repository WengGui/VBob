"""媒体类型、目录限定源与来源偏好的接口测试。"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient


def scan(client: TestClient, root_id: int) -> dict:
    response = client.post("/api/scans", json={"root_id": root_id})
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"succeeded", "failed", "canceled"}:
            return job
        time.sleep(0.05)
    raise AssertionError("scan timed out")


def make_root(
    client: TestClient,
    tmp_path: Path,
    name: str,
    *,
    category: str = "other",
    source_ids: list[int] | None = None,
    files: list[str] | None = None,
) -> tuple[dict, list[dict]]:
    """创建目录、写入文件并扫描，返回 (root, videos)。"""
    media = tmp_path / name
    media.mkdir()
    for filename in files or ["Movie 2026.mp4"]:
        (media / filename).write_bytes(b"video")
    client.put("/api/settings", json={"scan": {"min_size_mb": 0}})
    root = client.post(
        "/api/scan-roots",
        json={
            "path": str(media),
            "category": category,
            "source_ids": source_ids or [],
        },
    ).json()
    scan(client, root["id"])
    return root, client.get("/api/videos").json()["items"]


def test_root_category_and_video_filters(client: TestClient, tmp_path: Path) -> None:
    root, videos = make_root(client, tmp_path, "movies", category="movie")
    assert root["category"] == "movie"
    assert root["source_ids"] == []
    assert videos[0]["category"] == "movie"

    make_root(client, tmp_path, "anime", category="anime")

    counts = client.get("/api/videos/categories").json()
    assert counts["movie"] == 1
    assert counts["anime"] == 1
    assert counts["all"] == 2
    assert counts["jav"] == 0

    movie_items = client.get("/api/videos", params={"category": "movie"}).json()
    assert movie_items["total"] == 1
    assert movie_items["items"][0]["category"] == "movie"

    # 其它分类为空，返回 0 条而不是报错。
    assert client.get("/api/videos", params={"category": "jav"}).json()["total"] == 0
    # 非法分类返回 422。
    assert client.get("/api/videos", params={"category": "bogus"}).status_code == 422


def test_root_category_change_keeps_manual_video_category(
    client: TestClient, tmp_path: Path
) -> None:
    root, videos = make_root(client, tmp_path, "mixed", category="movie")
    video_id = videos[0]["id"]

    # 手动改成动漫后，目录改分类不再覆盖。
    response = client.put(f"/api/videos/{video_id}/category", json={"category": "anime"})
    assert response.status_code == 200, response.text
    assert response.json()["video"]["category"] == "anime"

    response = client.put(f"/api/scan-roots/{root['id']}", json={"category": "series"})
    assert response.status_code == 200, response.text
    assert client.get(f"/api/videos/{video_id}").json()["video"]["category"] == "anime"

    # 新增文件继承目录的新分类。
    (tmp_path / "mixed" / "Second 2024.mp4").write_bytes(b"video2")
    scan(client, root["id"])
    categories = {
        item["filename"]: item["category"] for item in client.get("/api/videos").json()["items"]
    }
    assert categories["Movie 2026.mp4"] == "anime"
    assert categories["Second 2024.mp4"] == "series"


def test_source_ids_are_ordered_and_cleaned_on_delete(
    client: TestClient, tmp_path: Path
) -> None:
    a = client.post(
        "/api/sources",
        json={
            "name": "source-a",
            "type": "query",
            "category": "movie",
            "request": {"url": "https://example.com/a?q={title}"},
            "extract": {"title": "json: title"},
        },
    ).json()
    b = client.post(
        "/api/sources",
        json={
            "name": "source-b",
            "type": "query",
            "category": "movie",
            "request": {"url": "https://example.com/b?q={title}"},
            "extract": {"title": "json: title"},
        },
    ).json()
    assert a["category"] == "movie"

    root, videos = make_root(
        client, tmp_path, "ordered", category="movie", source_ids=[b["id"], a["id"]]
    )
    assert root["source_ids"] == [b["id"], a["id"]]

    # 偏好源在删除源时一并清除。
    client.app.state.store.set_source_preference(videos[0]["id"], a["id"])
    assert (
        client.get(f"/api/videos/{videos[0]['id']}").json()["metadata"]["source_id"]
        == a["id"]
    )
    assert client.delete(f"/api/sources/{a['id']}").status_code == 204

    roots = client.get("/api/scan-roots").json()["items"]
    refreshed = next(item for item in roots if item["id"] == root["id"])
    assert refreshed["source_ids"] == [b["id"]]
    assert (
        client.get(f"/api/videos/{videos[0]['id']}").json()["metadata"]["source_id"]
        is None
    )


def test_invalid_category_values_are_rejected(client: TestClient, tmp_path: Path) -> None:
    media = tmp_path / "bad"
    media.mkdir()
    response = client.post(
        "/api/scan-roots", json={"path": str(media), "category": "bogus"}
    )
    assert response.status_code == 422

    response = client.post(
        "/api/sources",
        json={
            "name": "bad-category",
            "type": "query",
            "category": "bogus",
            "request": {"url": "https://example.com/?q={title}"},
            "extract": {"title": "json: title"},
        },
    )
    assert response.status_code == 422

    video_id = make_root(client, tmp_path, "video", category="other")[1][0]["id"]
    assert (
        client.put(f"/api/videos/{video_id}/category", json={"category": "bogus"}).status_code
        == 422
    )


def test_source_templates_include_categories(client: TestClient) -> None:
    items = client.get("/api/sources/templates").json()["items"]
    by_key = {item["key"]: item for item in items}
    assert {"tmdb-movie", "tmdb-series", "tmdb-anime", "shikimori-anime"} <= set(by_key)
    assert by_key["tmdb-movie"]["config"]["category"] == "movie"
    assert by_key["tmdb-anime"]["config"]["category"] == "anime"
    assert by_key["shikimori-anime"]["config"]["category"] == "anime"
    assert by_key["tmdb-movie"]["config"]["vars"]["api_key"] == ""

    created = client.post("/api/sources/templates/tmdb-movie")
    assert created.status_code == 201, created.text
    assert created.json()["category"] == "movie"
    # 同名源已存在时返回 409；未知模板返回 404。
    assert client.post("/api/sources/templates/tmdb-movie").status_code == 409
    assert client.post("/api/sources/templates/unknown").status_code == 404


def test_pick_scan_root_returns_selected_directory(
    client: TestClient, tmp_path: Path, monkeypatch
) -> None:
    """目录选择框返回的路径经过规范化后直接回填。"""
    picked = tmp_path / "picked"
    picked.mkdir()
    monkeypatch.setattr("vbob.api.pick_directory", lambda: str(picked))

    response = client.post("/api/scan-roots/pick")
    assert response.status_code == 200, response.text
    assert Path(response.json()["path"]) == picked.resolve()


def test_pick_scan_root_cancel_returns_null(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr("vbob.api.pick_directory", lambda: None)
    response = client.post("/api/scan-roots/pick")
    assert response.status_code == 200
    assert response.json()["path"] is None
