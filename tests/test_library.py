from __future__ import annotations

import os
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


def setup_video(client: TestClient, tmp_path: Path) -> tuple[int, int]:
    media = tmp_path / "media"
    media.mkdir()
    (media / "SSIS-001.mp4").write_bytes(b"video")
    client.put("/api/settings", json={"scan": {"min_size_mb": 0}})
    root = client.post("/api/scan-roots", json={"path": str(media)}).json()
    scan(client, root["id"])
    items = client.get("/api/videos").json()["items"]
    return root["id"], items[0]["id"]


def test_manual_edit_completeness_and_actresses(client: TestClient, tmp_path: Path) -> None:
    _, video_id = setup_video(client, tmp_path)

    response = client.patch(
        f"/api/videos/{video_id}/metadata",
        json={
            "version": 0,
            "title": "测试影片",
            "release_date": "2026-01-02",
            "runtime_sec": 5400,
            "tags": ["高清", "独家"],
            "actresses": [{"name": "测试演员"}],
            "censored": "censored",
            "country": "日本",
        },
    )
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["metadata"]["title"] == "测试影片"
    assert detail["metadata"]["is_complete"] is False  # cover still missing
    assert len(detail["actresses"]) == 1
    actress_id = detail["actresses"][0]["id"]
    assert detail["metadata"]["version"] > 0

    # Upload a cover and complete the video.
    cover = b"\xff\xd8\xff\xe0" + b"fake-jpeg-data"
    response = client.post(
        f"/api/videos/{video_id}/cover",
        files={"file": ("cover.jpg", cover, "image/jpeg")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["metadata"]["is_complete"] is True

    response = client.get(f"/api/videos/{video_id}/cover")
    assert response.status_code == 200
    assert response.content == cover

    # Actress list and manual fields.
    response = client.get("/api/actresses")
    assert response.status_code == 200
    actress = response.json()["items"][0]
    assert actress["name"] == "测试演员"
    assert actress["video_count"] == 1
    assert actress["is_complete"] is False

    response = client.patch(
        f"/api/actresses/{actress_id}",
        json={
            "version": actress["version"],
            "birth_date": "2000-01-01",
            "nationality": "日本",
            "height_cm": 160,
        },
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["birth_date"] == "2000-01-01"
    assert updated["is_complete"] is False

    response = client.post(
        f"/api/actresses/{actress_id}/cover",
        files={"file": ("cover.png", b"\x89PNG\r\n\x1a\nfake", "image/png")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_complete"] is True

    # Favorites.
    response = client.patch(f"/api/videos/{video_id}/favorite", json={"favorite": True})
    assert response.status_code == 200
    assert response.json()["video"]["favorite"] is True
    response = client.patch(f"/api/actresses/{actress_id}/favorite", json={"favorite": True})
    assert response.status_code == 200
    assert response.json()["favorite"] is True

    # Actress deletion is blocked while a video is linked.
    response = client.delete(f"/api/actresses/{actress_id}")
    assert response.status_code == 409
    assert response.json()["error"]["message"]

    assert client.delete(f"/api/videos/{video_id}").status_code == 204
    assert client.delete(f"/api/actresses/{actress_id}").status_code == 204


def test_version_conflict(client: TestClient, tmp_path: Path) -> None:
    _, video_id = setup_video(client, tmp_path)
    response = client.patch(
        f"/api/videos/{video_id}/metadata", json={"version": 0, "title": "A"}
    )
    version = response.json()["metadata"]["version"]
    response = client.patch(
        f"/api/videos/{video_id}/metadata", json={"version": version, "title": "B"}
    )
    assert response.status_code == 200
    stale = client.patch(
        f"/api/videos/{video_id}/metadata", json={"version": version, "title": "C"}
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "version_conflict"


def test_edit_and_scan_root_path_remap(client: TestClient, tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    (media / "ABP-123.mp4").write_bytes(b"video")
    client.put("/api/settings", json={"scan": {"min_size_mb": 0}})
    root = client.post(
        "/api/scan-roots", json={"path": str(media), "scan_interval_minutes": 15}
    ).json()
    assert root["scan_interval_minutes"] == 15
    scan(client, root["id"])
    video = client.get("/api/videos").json()["items"][0]
    old_path = video["path"]
    video_id = video["id"]

    renamed = tmp_path / "media-renamed"
    os.rename(media, renamed)

    response = client.put(
        f"/api/scan-roots/{root['id']}",
        json={"path": str(renamed), "scan_interval_minutes": 30},
    )
    assert response.status_code == 200, response.text
    updated_root = response.json()
    assert updated_root["scan_interval_minutes"] == 30

    detail = client.get(f"/api/videos/{video_id}").json()
    assert detail["video"]["id"] == video_id
    assert detail["video"]["path"] != old_path
    assert "media-renamed" in detail["video"]["path"]

    scan(client, root["id"])
    items = client.get("/api/videos").json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == video_id


def test_list_filters(client: TestClient, tmp_path: Path) -> None:
    _, video_id = setup_video(client, tmp_path)
    client.patch(
        f"/api/videos/{video_id}/metadata",
        json={"version": 0, "title": "Filter Me", "tags": ["rare"], "actresses": [{"name": "A"}]},
    )
    client.patch(f"/api/videos/{video_id}/favorite", json={"favorite": True})

    assert client.get("/api/videos", params={"favorite": "true"}).json()["total"] == 1
    assert client.get("/api/videos", params={"tag": "rare"}).json()["total"] == 1
    assert client.get("/api/videos", params={"complete": "false"}).json()["total"] == 1
    actress_id = client.get("/api/actresses").json()["items"][0]["id"]
    assert (
        client.get("/api/videos", params={"actress_id": actress_id}).json()["total"] == 1
    )
