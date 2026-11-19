from __future__ import annotations

import base64
import json
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

# JSON 接口用于验证详情请求、封面前缀和源顺序。
JSON_A = {
    "results": [
        {
            "id": 7,
            "title": "Source A",
            "overview": "A overview",
            "release_date": "2026-02-03",
            "poster_path": "/poster.jpg",
        }
    ]
}
JSON_B = {"results": [{"id": 8, "title": "Source B"}]}
DETAIL_JSON = {
    "runtime": 130,
    "genres": [{"name": "剧情"}, {"name": "喜剧"}],
    "production_companies": [{"name": "Studio A"}],
    "production_countries": [{"name": "中国"}],
}
# 记录测试期间的请求路径，用于断言源顺序与是否真的发起了请求。
REQUESTS: list[str] = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        split = urlsplit(self.path)
        path = unquote(split.path)
        REQUESTS.append(path)
        if path.startswith("/v/"):
            body = VIDEO_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif path.startswith("/actress/") or path.startswith("/star/"):
            body = ACTRESS_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif path == "/json/a":
            body = json.dumps(JSON_A, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
        elif path == "/json/b":
            body = json.dumps(JSON_B, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
        elif path == "/detail/7":
            body = json.dumps(DETAIL_JSON, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
        elif path in {"/cover.png", "/acover.png", "/poster.jpg"}:
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
    REQUESTS.clear()
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


def _query_source(name: str, url: str, *, category: str = "other", extract=None) -> dict:
    """构造一个最小可用的 JSON 查询源。"""
    return {
        "name": name,
        "enabled": True,
        "priority": 100,
        "type": "query",
        "category": category,
        "request": {"url": url, "timeout_ms": 5000},
        "extract": extract or {"title": "json: results[0].title"},
    }


def _scan_single_video(
    client: TestClient, tmp_path: Path, filename: str, *, category: str = "other"
) -> tuple[int, int]:
    """创建目录、扫描一个文件，返回 (root_id, video_id)。"""
    media = tmp_path / "media"
    media.mkdir()
    (media / filename).write_bytes(b"video")
    client.put("/api/settings", json={"scan": {"min_size_mb": 0}})
    root = client.post(
        "/api/scan-roots", json={"path": str(media), "category": category}
    ).json()
    job = client.post("/api/scans", json={"root_id": root["id"]}).json()
    wait_job(client, job["job_id"])
    video_id = client.get("/api/videos").json()["items"][0]["id"]
    return root["id"], video_id


def test_source_order_follows_root_selection(
    client: TestClient, tmp_path: Path, mock_site: str
) -> None:
    """目录限定的源按勾选顺序执行，而不是全局优先级。"""
    root_id, video_id = _scan_single_video(client, tmp_path, "Movie 2026.mp4")
    a = client.post(
        "/api/sources", json=_query_source("source-a", f"{mock_site}/json/a")
    ).json()
    b = client.post(
        "/api/sources", json=_query_source("source-b", f"{mock_site}/json/b")
    ).json()

    client.put(f"/api/scan-roots/{root_id}", json={"source_ids": [b["id"], a["id"]]})
    response = client.post(f"/api/videos/{video_id}/scrape", json={"force": True})
    wait_job(client, response.json()["job_id"])
    detail = client.get(f"/api/videos/{video_id}").json()
    assert detail["metadata"]["title"] == "Source B"
    # 两个源都会执行，来源按实际执行顺序记录；字段以先到者为准。
    assert detail["metadata"]["source_names"] == ["source-b", "source-a"]

    # 换顺序后，先执行的源写入的字段保持不变（先到先得）。
    client.put(f"/api/scan-roots/{root_id}", json={"source_ids": [a["id"], b["id"]]})
    response = client.post(f"/api/videos/{video_id}/scrape", json={"force": True})
    wait_job(client, response.json()["job_id"])
    detail = client.get(f"/api/videos/{video_id}").json()
    assert detail["metadata"]["title"] == "Source A"
    # 两个源都命中了，来源列表按执行顺序记录。
    assert detail["metadata"]["source_names"] == ["source-a", "source-b"]


def test_preferred_source_overrides_directory_and_can_be_cleared(
    client: TestClient, tmp_path: Path, mock_site: str
) -> None:
    """详情页记住的偏好源优先于目录配置；恢复自动后重新跟随目录。"""
    root_id, video_id = _scan_single_video(client, tmp_path, "Movie 2026.mp4")
    a = client.post(
        "/api/sources", json=_query_source("source-a", f"{mock_site}/json/a")
    ).json()
    b = client.post(
        "/api/sources", json=_query_source("source-b", f"{mock_site}/json/b")
    ).json()
    client.put(f"/api/scan-roots/{root_id}", json={"source_ids": [a["id"]]})

    response = client.post(
        f"/api/videos/{video_id}/scrape",
        json={"force": True, "source_id": b["id"], "remember_source": True},
    )
    wait_job(client, response.json()["job_id"])
    detail = client.get(f"/api/videos/{video_id}").json()
    assert detail["metadata"]["title"] == "Source B"
    assert detail["metadata"]["source_id"] == b["id"]

    # 清除偏好后按目录配置（source-a）执行。
    response = client.post(
        f"/api/videos/{video_id}/scrape",
        json={"force": True, "source_id": None, "remember_source": True},
    )
    wait_job(client, response.json()["job_id"])
    detail = client.get(f"/api/videos/{video_id}").json()
    assert detail["metadata"]["source_id"] is None
    assert detail["metadata"]["title"] == "Source A"


def test_category_isolates_sources(
    client: TestClient, tmp_path: Path, mock_site: str
) -> None:
    """电影目录不会执行 JAV 分类的源。"""
    _, video_id = _scan_single_video(
        client, tmp_path, "Movie 2026.mp4", category="movie"
    )
    client.post(
        "/api/sources",
        json=_query_source("jav-source", f"{mock_site}/json/a", category="jav"),
    )
    response = client.post(f"/api/videos/{video_id}/scrape", json={"force": True})
    wait_job(client, response.json()["job_id"])
    detail = client.get(f"/api/videos/{video_id}").json()
    assert detail["metadata"]["scrape_status"] == "no_match"
    assert REQUESTS == []  # 完全不发起请求

    client.post(
        "/api/sources",
        json=_query_source("movie-source", f"{mock_site}/json/a", category="movie"),
    )
    response = client.post(f"/api/videos/{video_id}/scrape", json={"force": True})
    wait_job(client, response.json()["job_id"])
    detail = client.get(f"/api/videos/{video_id}").json()
    assert detail["metadata"]["title"] == "Source A"


def test_detail_request_asset_base_and_helper_fields(
    client: TestClient, tmp_path: Path, mock_site: str
) -> None:
    """详情请求补全字段，_ 开头字段不入库，根相对封面按 asset_base_url 拼接。"""
    _, video_id = _scan_single_video(client, tmp_path, "Movie 2026.mp4")
    source = _query_source(
        "detail-source",
        f"{mock_site}/json/a",
        extract={
            "_movie_id": "json: results[0].id",
            "title": "json: results[0].title",
            "release_date": "json: results[0].release_date",
            "cover_url": "json: results[0].poster_path",
        },
    )
    source["asset_base_url"] = mock_site
    source["detail"] = {
        "url": f"{mock_site}/detail/{{_movie_id}}",
        "extract": {
            "runtime_sec": "json: runtime",
            "genres": "json: genres[*].name",
            "studio": "json: production_companies[0].name",
            "country": "json: production_countries[0].name",
        },
    }
    assert client.post("/api/sources", json=source).status_code == 201

    response = client.post(f"/api/videos/{video_id}/scrape", json={"force": True})
    wait_job(client, response.json()["job_id"])
    detail = client.get(f"/api/videos/{video_id}").json()
    metadata = detail["metadata"]
    assert metadata["title"] == "Source A"
    assert metadata["runtime_sec"] == 7800
    assert sorted(metadata["genres"]) == ["剧情", "喜剧"]
    assert metadata["studio"] == "Studio A"
    assert metadata["country"] == "中国"
    assert client.get(f"/api/videos/{video_id}/cover").content == PNG
    assert "_movie_id" not in (metadata["raw_payload"] or "")
    assert "/detail/7" in REQUESTS


def test_reset_clears_previous_source_fields(
    client: TestClient, tmp_path: Path, mock_site: str
) -> None:
    """切换源时 reset=true 会清空旧源写入的非手动字段。"""
    root_id, video_id = _scan_single_video(client, tmp_path, "Movie 2026.mp4")
    a = client.post(
        "/api/sources",
        json=_query_source(
            "source-a",
            f"{mock_site}/json/a",
            extract={
                "title": "json: results[0].title",
                "overview": "json: results[0].overview",
            },
        ),
    ).json()
    b = client.post(
        "/api/sources", json=_query_source("source-b", f"{mock_site}/json/b")
    ).json()
    client.put(f"/api/scan-roots/{root_id}", json={"source_ids": [a["id"]]})
    response = client.post(f"/api/videos/{video_id}/scrape", json={"force": True})
    wait_job(client, response.json()["job_id"])
    assert (
        client.get(f"/api/videos/{video_id}").json()["metadata"]["overview"]
        == "A overview"
    )

    response = client.post(
        f"/api/videos/{video_id}/scrape",
        json={
            "force": True,
            "source_id": b["id"],
            "remember_source": True,
            "reset": True,
        },
    )
    wait_job(client, response.json()["job_id"])
    metadata = client.get(f"/api/videos/{video_id}").json()["metadata"]
    assert metadata["title"] == "Source B"
    # 新源没有简介，旧源写入的简介已被清空。
    assert metadata["overview"] is None


def test_refresh_cover_uses_stored_url(
    client: TestClient, tmp_path: Path, mock_site: str
) -> None:
    """封面下载失败后可用已记录的远端地址重试，且不标记为手动封面。"""
    _, video_id = _scan_single_video(
        client, tmp_path, "One Piece 1999.mp4", category="anime"
    )
    store = client.app.state.store
    with store.db.transaction() as conn:
        store._ensure_metadata_row(conn, video_id)
        conn.execute(
            "UPDATE metadata SET cover_url=?, cover_local=NULL WHERE video_id=?",
            (f"{mock_site}/poster.jpg", video_id),
        )

    response = client.post(f"/api/videos/{video_id}/cover/refresh")
    assert response.status_code == 200, response.text
    metadata = response.json()["metadata"]
    assert metadata["cover_local"]
    # 自动重试不应把封面变成“手动字段”，否则后续刮削无法替换。
    assert "cover_local" not in metadata["manual_fields"]
    assert client.get(f"/api/videos/{video_id}/cover").content == PNG


def test_refresh_cover_requires_remote_url(client: TestClient, tmp_path: Path) -> None:
    _, video_id = _scan_single_video(client, tmp_path, "No Cover 2020.mp4")
    response = client.post(f"/api/videos/{video_id}/cover/refresh")
    assert response.status_code == 422
    assert "封面地址" in response.json()["error"]["message"]
