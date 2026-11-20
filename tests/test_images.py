"""封面下载的重试、尺寸兜底与校验测试。"""

from __future__ import annotations

import base64

import pytest

from vbob.errors import InvalidError
from vbob.images import MAX_IMAGE_BYTES, download_image

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2n2kAAAAASUVORK5CYII="
)


def test_download_image_retries_connection_reset(monkeypatch) -> None:
    """CDN 偶发重置连接时应当重试，而不是直接放弃封面。"""
    import vbob.images as images

    calls: list[str] = []

    def fake_fetch(url: str, proxy: str | None) -> bytes:
        calls.append(url)
        if len(calls) < 3:
            raise OSError("[WinError 10054] 远程主机强迫关闭了一个现有的连接")
        return PNG

    monkeypatch.setattr(images, "_fetch_once", fake_fetch)
    monkeypatch.setattr(images.time, "sleep", lambda _: None)

    assert download_image("https://example.com/poster.jpg") == PNG
    assert len(calls) == 3


def test_download_image_falls_back_to_other_size(monkeypatch) -> None:
    """主尺寸持续失败时，尝试 TMDB 的其他尺寸。"""
    import vbob.images as images

    calls: list[str] = []

    def fake_fetch(url: str, proxy: str | None) -> bytes:
        calls.append(url)
        if "/t/p/w500/" in url:
            raise OSError("reset")
        return PNG

    monkeypatch.setattr(images, "_fetch_once", fake_fetch)
    monkeypatch.setattr(images.time, "sleep", lambda _: None)

    data = download_image("https://image.tmdb.org/t/p/w500/poster.jpg")
    assert data == PNG
    assert any("/t/p/w780/" in url for url in calls)
    # w500 重试 3 次 + w780 一次成功。
    assert len(calls) == 4


def test_download_image_passes_source_proxy(monkeypatch) -> None:
    """源配置的代理需要传递给图片下载，保证走同一网络出口。"""
    import vbob.images as images

    seen: list[str | None] = []

    def fake_fetch(url: str, proxy: str | None) -> bytes:
        seen.append(proxy)
        return PNG

    monkeypatch.setattr(images, "_fetch_once", fake_fetch)
    assert download_image("https://example.com/poster.jpg", proxy="http://127.0.0.1:7890") == PNG
    assert seen == ["http://127.0.0.1:7890"]


def test_download_image_gives_up_after_retries(monkeypatch) -> None:
    import vbob.images as images

    def fake_fetch(url: str, proxy: str | None) -> bytes:
        raise OSError("reset")

    monkeypatch.setattr(images, "_fetch_once", fake_fetch)
    monkeypatch.setattr(images.time, "sleep", lambda _: None)

    with pytest.raises(InvalidError, match="下载封面失败"):
        download_image("https://example.com/poster.jpg")


def test_download_image_rejects_oversized(monkeypatch) -> None:
    import vbob.images as images

    def fake_fetch(url: str, proxy: str | None) -> bytes:
        return b"x" * (MAX_IMAGE_BYTES + 1)

    monkeypatch.setattr(images, "_fetch_once", fake_fetch)
    with pytest.raises(InvalidError, match="过大"):
        download_image("https://example.com/poster.jpg")


def test_download_image_rejects_non_http_url() -> None:
    with pytest.raises(InvalidError, match="http"):
        download_image("file:///etc/passwd")
