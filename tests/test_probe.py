"""刮削源连通性检测：信号换算、站内探测与接口落库。"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from vbob.probe import _base_url, probe_source, probe_sources, signal_level


class Handler(BaseHTTPRequestHandler):
    """任意路径返回 200，用于验证正常可达的源。"""

    def do_GET(self) -> None:  # noqa: N802
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # noqa: D102 - 静默测试日志
        return


class NotFoundHandler(Handler):
    """根路径也没有内容（返回 404），模拟部分 API 站点的根地址。"""

    def do_GET(self) -> None:  # noqa: N802
        body = b"not found"
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_server(handler: type[BaseHTTPRequestHandler]) -> str:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_address[1]}"


@pytest.fixture
def server():
    url = start_server(Handler)
    yield url


def test_signal_level_thresholds() -> None:
    assert signal_level(False, 100) == 0
    assert signal_level(True, None) == 0
    assert signal_level(True, 120) == 5
    assert signal_level(True, 300) == 5
    assert signal_level(True, 301) == 4
    assert signal_level(True, 800) == 4
    assert signal_level(True, 801) == 3
    assert signal_level(True, 1500) == 3
    assert signal_level(True, 1501) == 2
    assert signal_level(True, 3000) == 2
    assert signal_level(True, 3001) == 1
    assert signal_level(True, 60000) == 1


def test_base_url_extraction() -> None:
    assert _base_url("https://api.tmdb.org/3/search/movie?query={title}") == "https://api.tmdb.org/"
    assert _base_url("http://127.0.0.1:8080/api/x") == "http://127.0.0.1:8080/"
    # 缺协议、主机带占位符或空地址都无法探测。
    assert _base_url("") is None
    assert _base_url("example.com/search") is None
    assert _base_url("https://{host}/api") is None


def test_probe_reachable_source(server: str) -> None:
    result = probe_source({"request": {"url": f"{server}/search?q={{title}}"}})
    assert result["reachable"] is True
    assert result["status_code"] == 200
    assert result["level"] >= 1
    assert result["latency_ms"] is not None
    assert result["url"] == f"{server}/"
    assert "可达" in result["message"]
    # 结果自带检测时间，便于前端显示“上次检测”。
    assert result["checked_at"].endswith("Z")


def test_probe_accepts_error_status_as_reachable() -> None:
    """根路径 404 也说明网络通畅，只提示状态码。"""
    result = probe_source({"request": {"url": f"{start_server(NotFoundHandler)}/search"}})
    assert result["reachable"] is True
    assert result["status_code"] == 404
    assert result["level"] >= 1
    assert "HTTP 404" in result["message"]


def test_probe_unreachable_source() -> None:
    # 127.0.0.1 上关闭的端口：连接被拒绝，信号为 0。
    result = probe_source({"request": {"url": "http://127.0.0.1:1/x", "timeout_ms": 1000}})
    assert result["reachable"] is False
    assert result["level"] == 0
    assert result["latency_ms"] is None
    assert "无法连接" in result["message"] or "超时" in result["message"]


def test_probe_invalid_url_config() -> None:
    result = probe_source({"request": {"url": "example.com/search"}})
    assert result["reachable"] is False
    assert result["level"] == 0
    assert "源地址无效" in result["message"]

    # 整段地址都由上游提供的源（如演员源）没有固定域名，提示原因而不是假装不可达。
    result = probe_source({"request": {"url": "{actress_url}"}})
    assert result["reachable"] is False
    assert "占位符" in result["message"]


def test_probe_sources_keeps_order(server: str) -> None:
    configs = [
        {"request": {"url": f"{server}/a"}},
        {"request": {"url": "http://127.0.0.1:1/x", "timeout_ms": 500}},
        {"request": {"url": f"{server}/b"}},
    ]
    results = probe_sources(configs)
    assert len(results) == 3
    assert [item["reachable"] for item in results] == [True, False, True]
    assert probe_sources([]) == []


def test_probe_endpoint_persists_result(client: TestClient, server: str) -> None:
    source = client.post(
        "/api/sources",
        json={
            "name": "probe-me",
            "type": "query",
            "request": {"url": f"{server}/search?q={{title}}"},
            "extract": {"title": "json: title"},
        },
    ).json()

    response = client.post(f"/api/sources/{source['id']}/probe")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["source_id"] == source["id"]
    assert data["reachable"] is True

    # 结果写回数据库，重新打开设置页仍能显示信号条。
    stored = client.get("/api/sources").json()["items"][0]
    assert stored["last_test_at"] == data["checked_at"]
    assert stored["last_test_result"]["level"] == data["level"]


def test_probe_endpoint_unknown_source(client: TestClient) -> None:
    assert client.post("/api/sources/999/probe").status_code == 404


def test_probe_all_sources(client: TestClient, server: str) -> None:
    for name, url in (("ok-source", f"{server}/a"), ("bad-source", "http://127.0.0.1:1/x")):
        assert (
            client.post(
                "/api/sources",
                json={
                    "name": name,
                    "type": "query",
                    "request": {"url": url, "timeout_ms": 800},
                    "extract": {"title": "json: title"},
                },
            ).status_code
            == 201
        )

    response = client.post("/api/sources/probe")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 2
    by_name = {
        source["name"]: result["level"]
        for source, result in zip(client.get("/api/sources").json()["items"], items)
    }
    assert by_name["ok-source"] >= 1
    assert by_name["bad-source"] == 0
