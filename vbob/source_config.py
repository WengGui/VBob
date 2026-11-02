"""刮削源配置校验：把外部 YAML/JSON 规范化为引擎可用的配置对象。

校验覆盖源类型、请求地址、提取表达式前缀、默认值与校验器结构；
所有错误统一抛出 InvalidError，便于接口层原样返回给用户。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit

from .errors import InvalidError

# feature：按文件名特征拼接 URL；query：按标题搜索；actress：演员资料。
SOURCE_TYPES = {"feature", "query", "actress"}
# 提取表达式必须以这些前缀之一开头，决定使用哪种解析器。
EXTRACT_PREFIXES = {"css", "xpath", "json", "regex"}


def _non_empty_str(value: Any, field: str) -> str:
    """校验非空字符串并返回去掉首尾空白后的值。"""
    if not isinstance(value, str) or not value.strip():
        raise InvalidError(f"{field} 必须是非空字符串")
    return value.strip()


def validate_source_config(config: Any) -> dict[str, Any]:
    """校验并规范化源配置（入参应已从 YAML/JSON 解析）。

    返回新的配置字典，不修改调用方传入的对象。
    """
    if not isinstance(config, dict):
        raise InvalidError("源配置必须是 YAML/JSON 对象")
    # 深拷贝后再改写，避免副作用影响调用方。
    data = deepcopy(config)

    data["name"] = _non_empty_str(data.get("name"), "name")
    if len(data["name"]) > 64:
        raise InvalidError("name 长度不能超过 64 个字符")

    source_type = data.get("type")
    if source_type not in SOURCE_TYPES:
        raise InvalidError("type 必须是 feature、query 或 actress")
    if source_type == "feature":
        data["feature"] = _non_empty_str(data.get("feature"), "feature")

    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        raise InvalidError("enabled 必须是布尔值")
    data["enabled"] = enabled

    priority = data.get("priority", 100)
    if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 100000:
        raise InvalidError("priority 必须是 0-100000 的整数")
    data["priority"] = priority

    request = data.get("request")
    if not isinstance(request, dict):
        raise InvalidError("request 必须是对象")
    url = _non_empty_str(request.get("url"), "request.url")
    # 演员源允许纯占位符 URL；其余源必须是完整的 http(s) 地址。
    if url != "{actress_url}":
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise InvalidError("request.url 必须是 http(s) URL")
    request["url"] = url
    method = str(request.get("method", "GET")).upper()
    if method not in {"GET", "POST"}:
        raise InvalidError("request.method 只支持 GET/POST")
    request["method"] = method

    extract = data.get("extract")
    if not isinstance(extract, dict) or not extract:
        raise InvalidError("extract 必须是非空对象")
    for field, expression in extract.items():
        if not isinstance(field, str) or not field.strip():
            raise InvalidError("extract 的字段名必须是非空字符串")
        if isinstance(expression, dict):
            # 只有 actresses 支持结构化对象；其余字段必须是表达式字符串。
            if field != "actresses":
                raise InvalidError(f"extract.{field} 必须是非空字符串")
            unknown = set(expression) - {"selector", "name", "url"}
            if unknown:
                raise InvalidError(f"extract.actresses 含有未知字段: {', '.join(sorted(unknown))}")
            selector = expression.get("selector")
            if not isinstance(selector, str) or not selector.strip():
                raise InvalidError("extract.actresses.selector 必须是非空字符串")
            prefix = selector.strip().split(":", 1)[0].strip().lower()
            if prefix not in EXTRACT_PREFIXES:
                raise InvalidError(
                    "extract.actresses.selector 需要以 css: / xpath: / json: / regex: 开头"
                )
            for key in ("name", "url"):
                value = expression.get(key)
                if value is not None and not isinstance(value, str):
                    raise InvalidError(f"extract.actresses.{key} 必须是字符串")
            continue
        if not isinstance(expression, str) or not expression.strip():
            raise InvalidError(f"extract.{field} 必须是非空字符串")
        prefix = expression.strip().split(":", 1)[0].strip().lower()
        if prefix not in EXTRACT_PREFIXES:
            raise InvalidError(
                f"extract.{field} 需要以 css: / xpath: / json: / regex: 开头"
            )

    # validators 目前只做结构校验，具体规则由引擎消费。
    validators = data.get("validators", [])
    if not isinstance(validators, list) or not all(isinstance(item, dict) for item in validators):
        raise InvalidError("validators 必须是对象数组")
    data["validators"] = validators

    # defaults 是提取失败时的兜底值，只允许标量或数组。
    defaults = data.get("defaults", {})
    if not isinstance(defaults, dict):
        raise InvalidError("defaults 必须是对象")
    for key, value in defaults.items():
        if not isinstance(key, str) or not key.strip():
            raise InvalidError("defaults 的字段名必须是非空字符串")
        if not isinstance(value, (str, int, float, list)):
            raise InvalidError(f"defaults.{key} 必须是字符串、数字或数组")
    data["defaults"] = defaults

    return data
