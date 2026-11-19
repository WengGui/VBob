"""封面图片下载与落盘：限制大小、校验图片签名并生成稳定路径。

下载和保存前都会用 detect_image 校验真实文件类型，防止把 HTML
错误页或伪造扩展名的内容当作图片写入。
"""

from __future__ import annotations

import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .errors import InvalidError

# 单张封面大小上限，防止异常大文件占满磁盘。
MAX_IMAGE_BYTES = 10 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) VBob/0.1"
# CDN 偶发重置连接（WinError 10054），重试几次通常就能成功。
IMAGE_RETRIES = 3
IMAGE_BACKOFF_SEC = 0.8


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


def _image_variants(url: str) -> list[str]:
    """主地址之外再准备几个 TMDB 尺寸作为兜底；普通站点只返回原地址。"""
    variants = [url]
    if "/t/p/w500/" in url:
        variants.append(url.replace("/t/p/w500/", "/t/p/w780/", 1))
        variants.append(url.replace("/t/p/w500/", "/t/p/original/", 1))
    return variants


def download_image(url: str) -> bytes:
    """下载封面并校验协议、大小与图片签名，返回原始字节。"""
    parsed = urlsplit(url)
    # 仅允许 http(s)，避免 file:// 等本地协议被滥用。
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise InvalidError("封面 URL 必须是 http(s) 地址")
    headers = {
        "User-Agent": USER_AGENT,
        # 不声明 avif，避免 CDN 返回当前不支持校验的格式。
        "Accept": "image/webp,image/jpeg,image/png,*/*;q=0.8",
    }
    last_error: Exception | None = None
    data: bytes | None = None
    # 主地址重试若干次；仍然失败时换 TMDB 的其他尺寸再试，绕过偶发的 CDN 重置。
    for index, candidate in enumerate(_image_variants(url)):
        attempts = IMAGE_RETRIES if index == 0 else 1
        request = urllib.request.Request(candidate, headers=headers)
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    # 多读 1 字节，以便判断内容是否超过上限。
                    data = response.read(MAX_IMAGE_BYTES + 1)
                break
            except Exception as exc:  # noqa: BLE001 - retried, then surfaced
                last_error = exc
                if attempt < attempts - 1:
                    time.sleep(IMAGE_BACKOFF_SEC * (attempt + 1))
        if data is not None:
            break
    if data is None:
        raise InvalidError(f"下载封面失败: {last_error}") from last_error
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
