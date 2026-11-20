"""HTTP 请求相关的共享工具。

刮削引擎（scraper）和连通性探测（probe）都需要同一套浏览器请求头、
占位符填充与 Cookie 解析规则，集中在这里避免两边行为漂移。
"""

from __future__ import annotations

import re
from typing import Any

# 伪装成真实浏览器，部分站点（尤其是年龄验证页）会拒绝非浏览器 UA。
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
)
DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_UA,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}
# 配置模板中的 {name} 占位符；URL 占位符在填充时会做 URL 编码。
PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class SkipSource(Exception):
    """源配置缺少必要占位符或 URL 非法时抛出，用于静默跳过该源。"""


def fill_raw(template: str, values: dict[str, Any]) -> str:
    """把占位符替换为原始值（不做 URL 编码），用于请求体和请求头。"""
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = values.get(key)
        if value is None or value == "":
            raise SkipSource(f"缺少占位符 {{{key}}}")
        return str(value)

    return PLACEHOLDER.sub(replace, template)


def fill_json(value: Any, values: dict[str, Any]) -> Any:
    """递归填充 JSON 结构中的占位符，返回可直接序列化的新对象。"""
    if isinstance(value, dict):
        return {key: fill_json(item, values) for key, item in value.items()}
    if isinstance(value, list):
        return [fill_json(item, values) for item in value]
    if isinstance(value, str):
        return fill_raw(value, values)
    return value


def parse_cookies(value: Any) -> dict[str, str]:
    """把字典或 "a=1; b=2" 形式的 Cookie 配置统一解析为字典。"""
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    if isinstance(value, str) and value.strip():
        result: dict[str, str] = {}
        for part in value.split(";"):
            if "=" in part:
                key, val = part.split("=", 1)
                result[key.strip()] = val.strip()
        return result
    return {}
