"""封面图片下载与落盘：限制大小、校验图片签名并生成稳定路径。

下载和保存前都会用 detect_image 校验真实文件类型，防止把 HTML
错误页或伪造扩展名的内容当作图片写入。
"""

from __future__ import annotations

import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .errors import InvalidError

# 单张封面大小上限，防止异常大文件占满磁盘。
MAX_IMAGE_BYTES = 10 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) VBob/0.1"


def detect_image(data: bytes) -> tuple[str, str] | None:
    """根据文件头签名返回 (扩展名, MIME)，无法识别时返回 None。"""
    # 按文件头魔数判断真实格式，不信任 URL 扩展名。
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg", "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png", "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp", "image/webp"
    return None


def download_image(url: str) -> bytes:
    """下载封面并校验协议、大小与图片签名，返回原始字节。"""
    parsed = urlsplit(url)
    # 仅允许 http(s)，避免 file:// 等本地协议被滥用。
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise InvalidError("封面 URL 必须是 http(s) 地址")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            # 多读 1 字节，以便判断内容是否超过上限。
            data = response.read(MAX_IMAGE_BYTES + 1)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user
        raise InvalidError(f"下载封面失败: {exc}") from exc
    if len(data) > MAX_IMAGE_BYTES:
        raise InvalidError("封面文件过大（上限 10MB）")
    if detect_image(data) is None:
        raise InvalidError("不支持的图片格式（仅支持 jpeg/png/webp）")
    return data


def save_cover(data_dir: Path, kind: str, entity_id: int, data: bytes) -> str:
    """写入 data/covers/{kind}/{id}.{ext}，返回相对路径。"""
    detected = detect_image(data)
    if detected is None:
        raise InvalidError("不支持的图片格式（仅支持 jpeg/png/webp）")
    extension, _ = detected
    directory = data_dir / "covers" / kind
    directory.mkdir(parents=True, exist_ok=True)
    # 先删除同 id 的旧扩展名文件，避免切换格式后残留。
    for stale in directory.glob(f"{entity_id}.*"):
        if stale.is_file():
            stale.unlink(missing_ok=True)
    target = directory / f"{entity_id}{extension}"
    target.write_bytes(data)
    return f"covers/{kind}/{target.name}"
