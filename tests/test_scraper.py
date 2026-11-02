from __future__ import annotations

import base64
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from fastapi.testclient import TestClient

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2n2kAAAAASUVORK5CYII="
)

VIDEO_HTML = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<h1>Mock Title</h1>
<div class="date">2026-01-02</div>
<div class="runtime">120分</div>
<div class="tags"><span>标签A</span><span>标签B</span></div>
<div class="star-box"><a href="/star/a" title="演员A">演员A</a><a href="/star/b" title="演员B">演员B</a></div>
<div class="cover"><img src="/cover.png"></div>
<div class="code">SSIS-001</div>
</body></html>"""

ACTRESS_HTML = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<div class="birth">生日: 2000-01-01</div>
<div class="cover"><img src="/acover.png"></div>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        path = unquote(urlsplit(self.path).path)
        if path.startswith("/v/"):
            body = VIDEO_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif path.startswith("/actress/") or path.startswith("/star/"):
            body = ACTRESS_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif path in {"/cover.png", "/acover.png"}:
            body = PNG
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
        else:
            body = b"not found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return


@pytest.fixture
def mock_site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def wait_job(client: TestClient, job_id: str, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"succeeded", "failed", "canceled"}:
            return job
        time.sleep(0.05)
    raise AssertionError("scrape job timed out")


def test_scrape_video_and_actresses(client: TestClient, tmp_path: Path, mock_site: str) -> None:
    media = tmp_path / "media"
    media.mkdir()
    (media / "SSIS-001.mp4").write_bytes(b"video")
    client.put("/api/settings", json={"scan": {"min_size_mb": 0}})
    root = client.post("/api/scan-roots", json={"path": str(media)}).json()
    job = client.post("/api/scans", json={"root_id": root["id"]}).json()
    wait_job(client, job["job_id"])
    video_id = client.get("/api/videos").json()["items"][0]["id"]

    video_source = {
        "name": "mock-video",
        "enabled": True,
        "priority": 10,
        "type": "feature",
        "feature": "jav_code",
        "request": {"url": f"{mock_site}/v/{{jav_code}}", "timeout_ms": 5000},
        "extract": {
            "title": "css: h1@text",
            "release_date": "css: .date@text",
            "runtime_sec": "css: .runtime@text",
            "tags": "css: .tags span@text | array",
            "actresses": {
                "selector": "css: .star-box a",
                "name": "@title",
                "url": "@href",
            },
            "cover_url": "css: .cover img@src",
            "code": "css: .code@text",
        },
    }
    actress_source = {
        "name": "mock-actress",
        "enabled": True,
        "priority": 20,
        "type": "actress",
        "request": {"url": "{actress_url}", "timeout_ms": 5000},
        "extract": {
            "birth_date": "css: .birth@text",
            "cover_url": "css: .cover img@src",
        },
        "defaults": {"nationality": "日本"},
    }
    assert client.post("/api/sources", json=video_source).status_code == 201
    assert client.post("/api/sources", json=actress_source).status_code == 201

    response = client.post(f"/api/videos/{video_id}/scrape", json={"force": True})
    assert response.status_code == 202, response.text
    job = wait_job(client, response.json()["job_id"])
    assert job["status"] == "succeeded", job

    detail = client.get(f"/api/videos/{video_id}").json()
    metadata = detail["metadata"]
    assert metadata["title"] == "Mock Title"
    assert metadata["release_date"] == "2026-01-02"
    assert metadata["runtime_sec"] == 7200
    assert metadata["code"] == "SSIS-001"
    assert sorted(metadata["tags"]) == ["标签A", "标签B"]
    assert metadata["is_complete"] is True
    assert {actress["name"] for actress in detail["actresses"]} == {"演员A", "演员B"}

    cover = client.get(f"/api/videos/{video_id}/cover")
    assert cover.status_code == 200
    assert cover.content == PNG

    actresses = client.get("/api/actresses").json()["items"]
    assert len(actresses) == 2
    for actress in actresses:
        assert actress["birth_date"] == "2000-01-01"
        assert actress["nationality"] == "日本"
        assert actress["profile_url"] in {f"{mock_site}/star/a", f"{mock_site}/star/b"}
        assert actress["is_complete"] is True

    logs = client.get(f"/api/videos/{video_id}/scrape-logs").json()["items"]
    assert logs
    assert any(log["success"] for log in logs)


def test_scrape_without_sources_marks_no_match(
    client: TestClient, tmp_path: Path
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    (media / "ABP-123.mp4").write_bytes(b"video")
    client.put("/api/settings", json={"scan": {"min_size_mb": 0}})
    root = client.post("/api/scan-roots", json={"path": str(media)}).json()
    job = client.post("/api/scans", json={"root_id": root["id"]}).json()
    wait_job(client, job["job_id"])
    video_id = client.get("/api/videos").json()["items"][0]["id"]

    response = client.post(f"/api/videos/{video_id}/scrape", json={"force": True})
    wait_job(client, response.json()["job_id"])
    metadata = client.get(f"/api/videos/{video_id}").json()["metadata"]
    assert metadata["scrape_status"] == "no_match"


def test_scrape_uses_manual_code_when_extraction_missing(
    client: TestClient, tmp_path: Path, mock_site: str
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    # 文件名无法提取出标准番号，模拟用户之后手动修正 code 的情况。
    (media / "kfa55.com@MKMP527C.mp4").write_bytes(b"video")
    client.put("/api/settings", json={"scan": {"min_size_mb": 0}})
    root = client.post("/api/scan-roots", json={"path": str(media)}).json()
    job = client.post("/api/scans", json={"root_id": root["id"]}).json()
    wait_job(client, job["job_id"])
    video = client.get("/api/videos").json()["items"][0]
    assert "jav_code" not in video["features"]

    response = client.patch(
        f"/api/videos/{video['id']}/metadata",
        json={"version": 0, "code": "MKMP-527"},
    )
    assert response.status_code == 200, response.text

    source = {
        "name": "mock-video",
        "enabled": True,
        "priority": 10,
        "type": "feature",
        "feature": "jav_code",
        "request": {"url": f"{mock_site}/v/{{jav_code}}", "timeout_ms": 5000},
        "extract": {"title": "css: h1@text"},
    }
    assert client.post("/api/sources", json=source).status_code == 201

    response = client.post(f"/api/videos/{video['id']}/scrape", json={"force": True})
    job = wait_job(client, response.json()["job_id"])
    assert job["status"] == "succeeded", job

    metadata = client.get(f"/api/videos/{video['id']}").json()["metadata"]
    assert metadata["title"] == "Mock Title"
    # 手动修正的番号不会被源结果覆盖。
    assert metadata["code"] == "MKMP-527"
    assert metadata["scrape_status"] == "success"


def test_rescan_keeps_manual_code_and_scraped_metadata(
    client: TestClient, tmp_path: Path, mock_site: str
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    video_file = media / "WRONG-999.mp4"
    video_file.write_bytes(b"video")
    client.put("/api/settings", json={"scan": {"min_size_mb": 0}})
    root = client.post("/api/scan-roots", json={"path": str(media)}).json()
    job = client.post("/api/scans", json={"root_id": root["id"]}).json()
    wait_job(client, job["job_id"])
    video = client.get("/api/videos").json()["items"][0]
    assert video["features"]["jav_code"] == "WRONG-999"

    # 用户把提取错误的番号手动改成正确值。
    client.patch(
        f"/api/videos/{video['id']}/metadata",
        json={"version": 0, "code": "MKMP-527"},
    )
    source = {
        "name": "mock-video",
        "enabled": True,
        "priority": 10,
        "type": "feature",
        "feature": "jav_code",
        "request": {"url": f"{mock_site}/v/{{jav_code}}", "timeout_ms": 5000},
        "extract": {"title": "css: h1@text"},
    }
    client.post("/api/sources", json=source)
    response = client.post(f"/api/videos/{video['id']}/scrape", json={"force": True})
    wait_job(client, response.json()["job_id"])
    metadata = client.get(f"/api/videos/{video['id']}").json()["metadata"]
    assert metadata["code"] == "MKMP-527"
    assert metadata["title"] == "Mock Title"

    # 文件发生变化触发重新提取特征，再扫描一次：元数据和手动番号必须保留。
    video_file.write_bytes(b"changed video content")
    job = client.post("/api/scans", json={"root_id": root["id"]}).json()
    wait_job(client, job["job_id"])
    after = client.get(f"/api/videos/{video['id']}").json()
    assert after["metadata"]["code"] == "MKMP-527"
    assert after["metadata"]["title"] == "Mock Title"
    assert after["metadata"]["scrape_status"] == "success"
    # 文件名中仍然是错误番号，但记录没有被重新刮削或覆盖。
    assert after["video"]["features"]["jav_code"] == "WRONG-999"
