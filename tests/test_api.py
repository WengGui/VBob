from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient


def wait_for_job(client: TestClient, job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] in {"succeeded", "failed", "canceled"}:
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish in time")


def test_scan_and_list(client: TestClient, tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    (media / "SSIS-001.mp4").write_bytes(b"a")
    (media / "Some.Movie.2023.mkv").write_bytes(b"b")

    response = client.put("/api/settings", json={"scan": {"min_size_mb": 0}})
    assert response.status_code == 200, response.text

    response = client.post("/api/scan-roots", json={"path": str(media)})
    assert response.status_code == 201, response.text
    root = response.json()

    response = client.post("/api/scans", json={})
    assert response.status_code == 202, response.text
    job = wait_for_job(client, response.json()["job_id"])
    assert job["status"] == "succeeded", job
    assert job["total"] == 2
    assert job["done"] == 2

    response = client.get("/api/videos")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    by_name = {item["filename"]: item for item in payload["items"]}
    assert by_name["SSIS-001.mp4"]["features"]["jav_code"] == "SSIS-001"
    assert by_name["SSIS-001.mp4"]["present"] is True
    assert by_name["SSIS-001.mp4"]["metadata"] is None

    response = client.get("/api/videos", params={"q": "SSIS"})
    assert response.json()["total"] == 1

    video_id = by_name["SSIS-001.mp4"]["id"]
    response = client.get(f"/api/videos/{video_id}")
    assert response.status_code == 200
    detail = response.json()
    assert detail["video"]["filename"] == "SSIS-001.mp4"
    assert detail["metadata"] is None

    (media / "SSIS-001.mp4").unlink()
    response = client.post("/api/scans", json={"root_id": root["id"]})
    wait_for_job(client, response.json()["job_id"])
    response = client.get("/api/videos", params={"present": "false"})
    assert response.json()["total"] == 1


def test_scan_root_overlap_conflict(client: TestClient, tmp_path: Path) -> None:
    media = tmp_path / "media"
    nested = media / "nested"
    nested.mkdir(parents=True)
    assert client.post("/api/scan-roots", json={"path": str(media)}).status_code == 201
    response = client.post("/api/scan-roots", json={"path": str(nested)})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_scan_requires_enabled_root(client: TestClient) -> None:
    response = client.post("/api/scans", json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_invalid_clean_rule_rejected(client: TestClient) -> None:
    response = client.put("/api/settings", json={"scraping": {"clean_rules": ["("]}})
    assert response.status_code == 422
    assert "清洗正则" in response.json()["error"]["message"]


def test_error_envelope_for_missing_video(client: TestClient) -> None:
    response = client.get("/api/videos/999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
