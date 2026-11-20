"""刮削源连通性探测。

只请求源站点的根地址，用来判断 DNS、TCP、TLS 与 HTTP 是否通畅，
不依赖具体视频，也不会因为缺少番号/标题占位符而跳过。
结果按响应耗时换算成 0-5 格信号，前端用信号条展示。

注意：
- 请求头中依赖视频字段的占位符（如 ``Bearer {api_key}`` 缺失时）会被忽略，
  其余能解析的头照常发送，尽量还原真实刮削时的网络路径；
- 任何 HTTP 响应（包括 4xx/5xx）都算“网络可达”，状态码只用于提示，
  因为很多站点根路径本来就没有内容。
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from .db import utc_now
from .http_utils import DEFAULT_HEADERS, SkipSource, fill_raw, parse_cookies

# 未配置超时时使用的探测超时（秒）；配置值上限为 15 秒，避免设置页长时间转圈。
DEFAULT_PROBE_TIMEOUT = 8.0
MAX_PROBE_TIMEOUT = 15.0
# 每档信号对应的耗时上限（毫秒）：依次为 5/4/3/2 格，超过最后一档记 1 格。
SIGNAL_THRESHOLDS = (300, 800, 1500, 3000)
# 批量检测时并发请求数上限，避免一次性对同一网络发起过多连接。
MAX_PROBE_WORKERS = 5


def signal_level(reachable: bool, latency_ms: float | None) -> int:
    """把可达性与耗时换算成信号格数（0 表示不可达或超时）。"""
    if not reachable or latency_ms is None:
        return 0
    for index, limit in enumerate(SIGNAL_THRESHOLDS):
        if latency_ms <= limit:
            return 5 - index
    return 1


def probe_source(config: dict[str, Any]) -> dict[str, Any]:
    """探测单个源的网络连通性，返回可直接返回给前端并落库的结果。"""
    request = config.get("request") or {}
    raw_url = str(request.get("url") or "")
    base_url = _base_url(raw_url)
    if base_url is None:
        # 演员源常把整段地址交给上游（如 {actress_url}），此时没有固定站点可探测。
        message = (
            "源地址含占位符，无法确定站点域名"
            if "{" in raw_url
            else "源地址无效，无法解析出站点地址"
        )
        return _result(False, None, None, message)

    headers = dict(DEFAULT_HEADERS)
    values = dict(config.get("vars") or {})
    for key, value in (request.get("headers") or {}).items():
        text = str(value)
        if "{" in text:
            try:
                text = fill_raw(text, values)
            except SkipSource:
                # 缺少密钥等占位符时跳过该头，其他头仍可完成连通性判断。
                continue
        headers[str(key)] = text

    timeout = _timeout(request)
    proxy = request.get("proxy") or None
    started = time.perf_counter()
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers=headers,
            cookies=parse_cookies(request.get("cookies")),
            proxy=proxy,
            trust_env=False,
        ) as client:
            # 只读取响应头，不等整个页面下载完，耗时更接近真实首包延迟。
            with client.stream("GET", base_url) as response:
                latency_ms = round((time.perf_counter() - started) * 1000)
                status_code = response.status_code
    except Exception as exc:  # noqa: BLE001 - 探测失败原因需要回显给用户
        return _result(
            False, None, None, _error_message(exc, timeout), base_url=base_url
        )

    level = signal_level(True, latency_ms)
    return {
        "reachable": True,
        "level": level,
        "latency_ms": latency_ms,
        "status_code": status_code,
        "message": f"可达 · {latency_ms} ms · HTTP {status_code}",
        "url": base_url,
        "checked_at": utc_now(),
    }


def probe_sources(configs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """并发探测多个源，返回顺序与入参一致。"""
    if not configs:
        return []
    with ThreadPoolExecutor(max_workers=min(MAX_PROBE_WORKERS, len(configs))) as pool:
        return list(pool.map(probe_source, configs))


def _result(
    reachable: bool,
    latency_ms: int | None,
    status_code: int | None,
    message: str,
    *,
    base_url: str | None = None,
) -> dict[str, Any]:
    """组装探测结果，保证字段结构在所有分支下一致。"""
    return {
        "reachable": reachable,
        "level": signal_level(reachable, latency_ms),
        "latency_ms": latency_ms,
        "status_code": status_code,
        "message": message,
        "url": base_url,
        "checked_at": utc_now(),
    }


def _base_url(url: str) -> str | None:
    """从源配置的请求地址中提取 scheme://host，作为探测目标。"""
    url = url.strip()
    if not url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    # 主机名连带占位符（如 https://{host}/）无法在不知道视频的情况下补全。
    if "{" in parts.netloc or "}" in parts.netloc:
        return None
    return urlunsplit((parts.scheme, parts.netloc, "/", "", ""))


def _timeout(request: dict[str, Any]) -> float:
    """探测超时：沿用源配置的超时，未配置时使用默认值。"""
    try:
        configured = float(request.get("timeout_ms", 0) or 0) / 1000
    except (TypeError, ValueError):
        configured = 0.0
    if configured <= 0:
        return DEFAULT_PROBE_TIMEOUT
    return min(MAX_PROBE_TIMEOUT, configured)


def _error_message(exc: Exception, timeout: float) -> str:
    """把异常转成简短的中文失败原因。"""
    if isinstance(exc, httpx.TimeoutException):
        return f"连接超时（{timeout:g} 秒）"
    if isinstance(exc, httpx.ConnectError):
        detail = str(exc).strip()
        return f"无法连接：{_short(detail or type(exc).__name__)}"
    return _short(f"{type(exc).__name__}: {exc}")


def _short(text: str, limit: int = 120) -> str:
    """截断过长的异常信息，避免撑爆设置页提示。"""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
