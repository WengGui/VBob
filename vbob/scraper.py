from __future__ import annotations

import html
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import httpx
import jmespath
from charset_normalizer import from_bytes
from parsel import Selector

from .errors import JobCanceled
from .images import download_image, save_cover
from .store import Store

log = logging.getLogger(__name__)

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
DEFAULT_DENY = ("404", "not found", "page not found", "検索結果", "エラー", "找不到")
PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_LAST_REQUEST: dict[str, float] = {}

VIDEO_FIELDS = {
    "title", "original_title", "overview", "release_date", "year", "runtime_sec",
    "genres", "tags", "code", "studio", "series", "director", "censored",
    "country", "cover_url",
}
ACTRESS_FIELDS = {
    "birth_date", "nationality", "cover_url", "profile_url", "height_cm",
    "bust_cm", "waist_cm", "hips_cm", "cup", "aliases",
}


class _SkipSource(Exception):
    pass


@dataclass
class SourceResult:
    source_name: str
    fields: dict[str, Any]
    actresses: list[dict[str, str]]
    matched_by: str
    raw: str


class SourceRunner:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def run(
        self, source: dict[str, Any], values: dict[str, Any]
    ) -> tuple[SourceResult | None, str | None]:
        config = source["config"]
        request = config.get("request") or {}
        try:
            url = self._fill_placeholders(str(request.get("url", "")), values)
        except _SkipSource as exc:
            return None, str(exc)

        method = str(request.get("method", "GET")).upper()
        headers = dict(DEFAULT_HEADERS)
        headers.update(
            {str(k): str(v) for k, v in (request.get("headers") or {}).items()}
        )
        cookies = _parse_cookies(request.get("cookies"))
        timeout = max(1.0, float(request.get("timeout_ms", 10000)) / 1000)
        retries = int((request.get("retry") or {}).get("max", 1))
        proxy = request.get("proxy") or None
        encoding = str(request.get("encoding", "auto") or "auto")

        self._throttle(url, request.get("rate_limit") or {})

        last_error = ""
        response: httpx.Response | None = None
        for attempt in range(retries + 1):
            try:
                with httpx.Client(
                    follow_redirects=True,
                    timeout=timeout,
                    headers=headers,
                    cookies=cookies,
                    proxy=proxy,
                    trust_env=False,
                ) as client:
                    response = client.request(method, url)
                if response.status_code >= 400:
                    last_error = f"HTTP {response.status_code}"
                else:
                    break
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(min(2.0, 0.5 * (attempt + 1)))
        if response is None or response.status_code >= 400:
            return None, last_error or "请求失败"

        text = _decode(response.content, response, encoding)
        if "driver-verify" in str(response.url):
            return None, "站点要求年龄验证，请配置有效 Cookies 或更换源"
        selector = Selector(text=text, base_url=str(response.url))
        json_data: Any = None
        extract = config.get("extract") or {}

        fields: dict[str, Any] = {}
        actress_specs: list[dict[str, str]] = []
        actress_names: list[str] = []
        warnings: list[str] = []

        for field, expression in extract.items():
            try:
                if field == "actresses" and isinstance(expression, dict):
                    actress_specs = self._extract_structured_actresses(
                        selector, expression, str(response.url), config
                    )
                    actress_names = [item["name"] for item in actress_specs if item.get("name")]
                    continue
                if not isinstance(expression, str):
                    continue
                expression = expression.strip()
                multi = expression.lower().endswith("| array")
                if multi:
                    expression = expression[: -len("| array")].strip()
                if expression.startswith("json:") and json_data is None:
                    json_data = json.loads(text)
                value = _extract_expression(
                    expression, selector, json_data, text, multi
                )
                normalized = _normalize_field(field, value, str(response.url), config)
                if normalized is None or normalized == [] or normalized == "":
                    continue
                if field == "actresses":
                    if isinstance(normalized, list):
                        actress_names = [str(item) for item in normalized if str(item).strip()]
                    else:
                        actress_names = _split_list(str(normalized))
                    continue
                fields[field] = normalized
            except Exception as exc:  # noqa: BLE001 - one bad field should not kill the source
                warnings.append(f"{field}: {exc}")

        deny = tuple(config.get("deny_title_patterns") or DEFAULT_DENY)
        title = fields.get("title")
        if title and any(pattern.lower() in str(title).lower() for pattern in deny):
            return None, f"疑似错误页：{title}"

        for field, default in (config.get("defaults") or {}).items():
            if field in fields or field == "actresses":
                continue
            normalized_default = _normalize_field(
                field, default, str(response.url), config
            )
            if normalized_default not in (None, "", []):
                fields[field] = normalized_default

        if not fields and not actress_names:
            message = "未提取到任何字段"
            if warnings:
                message += f"（{warnings[0]}）"
            return None, message

        if actress_names and not actress_specs:
            actress_specs = [{"name": name} for name in actress_names]

        raw = json.dumps(
            {"fields": fields, "actresses": actress_specs or actress_names},
            ensure_ascii=False,
        )[:20000]
        matched_by = (
            str(config.get("feature")) if config.get("type") == "feature" else
            "actress_name" if config.get("type") == "actress" else "title"
        )
        return (
            SourceResult(
                source_name=source["name"],
                fields=fields,
                actresses=actress_specs,
                matched_by=matched_by,
                raw=raw,
            ),
            None,
        )

    @staticmethod
    def _fill_placeholders(template: str, values: dict[str, Any]) -> str:
        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            value = values.get(key)
            if value is None or value == "":
                raise _SkipSource(f"缺少占位符 {{{key}}}")
            text = str(value)
            if key == "actress_url" or key.endswith("_url"):
                if urlsplit(text).scheme not in {"http", "https"}:
                    raise _SkipSource(f"占位符 {{{key}}} 不是有效 URL")
                return text
            return quote(text, safe="")

        return PLACEHOLDER.sub(replace, template)

    @staticmethod
    def _throttle(url: str, rate_limit: dict[str, Any]) -> None:
        try:
            qps = float(rate_limit.get("qps", 0) or 0)
        except (TypeError, ValueError):
            qps = 0
        if qps <= 0:
            return
        host = urlsplit(url).netloc
        last = _LAST_REQUEST.get(host, 0.0)
        wait = (1.0 / qps) - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        _LAST_REQUEST[host] = time.monotonic()

    def _extract_structured_actresses(
        self,
        selector: Selector,
        spec: dict[str, Any],
        base_url: str,
        config: dict[str, Any],
    ) -> list[dict[str, str]]:
        selector_expr = str(spec.get("selector", "")).strip()
        if selector_expr.startswith("css:"):
            nodes = selector.css(selector_expr[4:].strip())
        elif selector_expr.startswith("xpath:"):
            nodes = selector.xpath(selector_expr[6:].strip())
        else:
            nodes = selector.css(selector_expr)
        name_expr = str(spec.get("name") or "@text")
        url_expr = str(spec.get("url") or "@href")
        result: list[dict[str, str]] = []
        for node in nodes:
            name = _clean_text(_node_value(node, name_expr))
            url = _clean_text(_node_value(node, url_expr))
            if not name:
                continue
            item = {"name": name}
            if url:
                item["url"] = _absolute_url(url, base_url, config)
            result.append(item)
        return result


class Scraper:
    def __init__(self, store: Store, data_dir: Path, job_id: str | None = None) -> None:
        self.store = store
        self.data_dir = data_dir
        self.job_id = job_id
        self.runner = SourceRunner(data_dir)

    def _sources(self) -> list[dict[str, Any]]:
        return [source for source in self.store.list_sources() if source["enabled"]]

    def scrape_video(
        self,
        video_id: int,
        *,
        force: bool = False,
        overwrite_manual: bool = False,
    ) -> dict[str, Any]:
        detail = self.store.get_video(video_id)
        video = detail["video"]
        meta = detail["metadata"] or {}
        if meta.get("is_complete") and not force:
            return {"status": "skipped", "message": "资料已完整"}

        features = video.get("features") or {}
        values = dict(features)
        values["title"] = meta.get("title") or features.get("title")
        values["year"] = meta.get("year") or features.get("year")
        values["code"] = meta.get("code") or features.get("jav_code")
        manual = set(meta.get("manual_fields") or [])
        sources = self._sources()
        feature_sources = [
            source for source in sources if source["config"].get("type") == "feature"
        ]
        query_sources = [
            source for source in sources if source["config"].get("type") == "query"
        ]

        accumulated: dict[str, Any] = {}
        actress_refs: list[dict[str, str]] = []
        actress_names: list[str] = []
        matched_sources: list[str] = []
        matched_by = ""
        errors: list[str] = []

        for source in [*feature_sources, *query_sources]:
            config = source["config"]
            source_type = config.get("type")
            if source_type == "feature" and not values.get(config.get("feature")):
                continue
            if source_type == "query" and not values.get("title"):
                continue
            result, error = self.runner.run(source, values)
            if error:
                errors.append(f"{source['name']}: {error}")
                log.warning(
                    "scrape video=%s source=%s failed: %s", video_id, source["name"], error
                )
                self.store.log_scrape(
                    video_id, self.job_id, source["name"], str(config.get("feature") or ""),
                    False, error,
                )
                continue
            assert result is not None
            for key, value in result.fields.items():
                if key not in accumulated and value not in (None, "", []):
                    accumulated[key] = value
            if result.actresses and not actress_refs:
                actress_refs = [
                    item for item in result.actresses if item.get("name")
                ]
                actress_names = [item["name"] for item in actress_refs]
            matched_sources.append(source["name"])
            if not matched_by:
                matched_by = result.matched_by
            log.info(
                "scrape video=%s source=%s ok fields=%s actresses=%s",
                video_id, source["name"], sorted(result.fields), actress_names,
            )
            self.store.log_scrape(
                video_id, self.job_id, source["name"], result.matched_by, True,
                f"提取字段: {', '.join(sorted(result.fields))}"
                + (f"；演员: {', '.join(actress_names)}" if actress_names else ""),
            )

        if not matched_sources:
            status = "failed" if errors else "no_match"
            self.store.mark_video_scrape_status(video_id, status)
            return {
                "status": status,
                "message": errors[0] if errors else "没有源匹配到数据",
            }

        cover_url = accumulated.get("cover_url")
        if cover_url and ("cover_local" not in manual or overwrite_manual):
            try:
                data = download_image(str(cover_url))
                accumulated["cover_local"] = save_cover(
                    self.data_dir, "videos", video_id, data
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"封面下载失败: {exc}")
                log.warning("cover download failed video=%s: %s", video_id, exc)

        raw_payload = json.dumps(
            {"sources": matched_sources, "fields": accumulated, "actresses": actress_names},
            ensure_ascii=False,
        )[:20000]
        self.store.merge_video_result(
            video_id,
            accumulated,
            source_name=matched_sources[0],
            matched_by=matched_by,
            actresses=actress_refs or None,
            raw_payload=raw_payload,
            overwrite_manual=overwrite_manual,
        )
        log.info(
            "scrape video=%s done sources=%s fields=%s",
            video_id, matched_sources, sorted(accumulated),
        )

        updated = self.store.get_video(video_id)
        for actress in updated.get("actresses", []):
            try:
                self.scrape_actress(
                    int(actress["id"]), overwrite_manual=overwrite_manual
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"演员 {actress['name']} 刮削失败: {exc}")
                log.warning("actress scrape failed actress=%s: %s", actress["id"], exc)

        return {
            "status": "success",
            "sources": matched_sources,
            "message": f"使用 {', '.join(matched_sources)} 更新了 {len(accumulated)} 个字段",
            "errors": errors,
        }

    def scrape_actress(
        self,
        actress_id: int,
        *,
        force: bool = False,
        overwrite_manual: bool = False,
    ) -> dict[str, Any]:
        detail = self.store.get_actress(actress_id)
        actress = detail["actress"]
        if actress.get("is_complete") and not force:
            return {"status": "skipped"}
        sources = [
            source for source in self._sources()
            if source["config"].get("type") == "actress"
        ]
        if not sources:
            return {"status": "no_source"}

        values = {
            "actress_name": actress["name"],
            "name": actress["name"],
            "actress_url": actress.get("profile_url") or "",
        }
        accumulated: dict[str, Any] = {}
        matched_sources: list[str] = []
        errors: list[str] = []
        for source in sources:
            result, error = self.runner.run(source, values)
            if error:
                errors.append(f"{source['name']}: {error}")
                log.warning(
                    "scrape actress=%s source=%s failed: %s",
                    actress_id, source["name"], error,
                )
                self.store.log_scrape(
                    0, self.job_id, source["name"], "actress_name", False, error
                )
                continue
            assert result is not None
            for key, value in result.fields.items():
                if key in ACTRESS_FIELDS and key not in accumulated:
                    accumulated[key] = value
            matched_sources.append(source["name"])
            self.store.log_scrape(
                0, self.job_id, source["name"], "actress_name", True,
                f"演员 {actress['name']} 提取字段: {', '.join(sorted(result.fields))}",
            )
        if not matched_sources:
            return {"status": "failed", "errors": errors}

        actress_url = str(values.get("actress_url") or "")
        if actress_url:
            accumulated.setdefault("profile_url", actress_url)

        cover_url = accumulated.get("cover_url")
        if cover_url:
            try:
                data = download_image(str(cover_url))
                accumulated["cover_local"] = save_cover(
                    self.data_dir, "actresses", actress_id, data
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"演员封面下载失败: {exc}")
                log.warning("actress cover failed actress=%s: %s", actress_id, exc)

        raw_payload = json.dumps(
            {"sources": matched_sources, "fields": accumulated}, ensure_ascii=False
        )[:20000]
        self.store.merge_actress_result(
            actress_id,
            accumulated,
            source_name=matched_sources[0],
            raw_payload=raw_payload,
            overwrite_manual=overwrite_manual,
        )
        log.info(
            "scrape actress=%s done sources=%s fields=%s",
            actress_id, matched_sources, sorted(accumulated),
        )
        return {"status": "success", "sources": matched_sources, "errors": errors}

    def scrape_root(
        self,
        root_id: int,
        *,
        force: bool = False,
        overwrite_manual: bool = False,
        cancel_event: Any = None,
        progress: Any = None,
    ) -> dict[str, int]:
        video_ids = self.store.list_video_ids_for_scrape(root_id, force=force)
        total = len(video_ids)
        counts = {"success": 0, "no_match": 0, "failed": 0, "skipped": 0, "errors": 0}
        progress_cb = progress or (lambda **_: None)
        progress_cb(done=0, total=total, message=f"准备刮削 {total} 个视频")
        for index, video_id in enumerate(video_ids, start=1):
            if cancel_event is not None and cancel_event.is_set():
                raise JobCanceled()
            try:
                outcome = self.scrape_video(
                    video_id, force=force, overwrite_manual=overwrite_manual
                )
                status = outcome.get("status", "failed")
                if status in counts:
                    counts[status] += 1
                if outcome.get("errors"):
                    counts["errors"] += len(outcome["errors"])
            except Exception as exc:  # noqa: BLE001 - continue with the next video
                counts["failed"] += 1
                counts["errors"] += 1
                log.exception("batch scrape failed video=%s", video_id)
                self.store.log_scrape(
                    video_id, self.job_id, "batch", "", False, f"{type(exc).__name__}: {exc}"
                )
            progress_cb(
                done=index,
                total=total,
                failed=counts["failed"],
                message=(
                    f"已处理 {index}/{total}：成功 {counts['success']}，"
                    f"无匹配 {counts['no_match']}，失败 {counts['failed']}"
                ),
            )
        return counts


def _parse_cookies(value: Any) -> dict[str, str]:
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


def _decode(content: bytes, response: httpx.Response, setting: str) -> str:
    if setting and setting.lower() != "auto":
        try:
            return content.decode(setting, errors="replace")
        except LookupError:
            pass
    charset = response.charset_encoding
    if charset:
        try:
            return content.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            pass
    match = re.search(rb"charset=[\"']?([\w-]+)", content[:8192], re.IGNORECASE)
    if match:
        try:
            return content.decode(match.group(1).decode("ascii"), errors="replace")
        except (LookupError, UnicodeDecodeError, UnicodeEncodeError):
            pass
    best = from_bytes(content).best()
    if best is not None:
        return str(best)
    return content.decode("utf-8", errors="replace")


def _extract_expression(
    expression: str,
    selector: Selector,
    json_data: Any,
    text: str,
    multi: bool,
) -> Any:
    expression = expression.strip()
    if expression.startswith("css:"):
        return _css_values(selector, expression[4:].strip(), multi)
    if expression.startswith("xpath:"):
        return _xpath_values(selector, expression[6:].strip(), multi)
    if expression.startswith("json:"):
        result = jmespath.search(expression[5:].strip(), json_data)
        if multi and isinstance(result, list):
            return result
        return result
    if expression.startswith("regex:"):
        match = re.search(expression[6:].strip(), text, re.IGNORECASE | re.MULTILINE)
        if not match:
            return None
        return match.group(1) if match.groups() else match.group(0)
    raise ValueError("未知提取前缀")


def _css_values(node: Selector, expression: str, multi: bool) -> Any:
    selector = expression.strip()
    attr = "text"
    if "@" in selector:
        selector, attr = selector.rsplit("@", 1)
        selector = selector.strip()
        attr = attr.strip()
    if not selector:
        raise ValueError("CSS 选择器为空")
    if attr in {"text", ""}:
        css = selector if "::" in selector else f"{selector}::text"
    else:
        css = f"{selector}::attr({attr})"
    values = [_clean_text(value) for value in node.css(css).getall()]
    values = [value for value in values if value]
    if multi:
        return values
    return values[0] if values else None


def _xpath_values(node: Selector, expression: str, multi: bool) -> Any:
    values = [_clean_text(value) for value in node.xpath(expression).getall() if isinstance(value, str)]
    values = [value for value in values if value]
    if not values:
        values = [_clean_text(value) for value in node.xpath(f"string({expression})").getall()]
        values = [value for value in values if value]
    if multi:
        return values
    return values[0] if values else None


def _node_value(node: Selector, expression: str) -> str:
    expression = expression.strip() or "@text"
    if expression.startswith("@"):
        attr = expression[1:]
        if attr in {"text", ""}:
            return node.xpath("string(.)").get() or ""
        return node.xpath(f"string(@{attr})").get() or ""
    if expression.startswith("css:"):
        return str(_css_values(node, expression[4:].strip(), False) or "")
    if expression.startswith("xpath:"):
        return str(_xpath_values(node, expression[6:].strip(), False) or "")
    return str(_css_values(node, expression, False) or "")


def _normalize_field(
    field: str, value: Any, base_url: str, config: dict[str, Any]
) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict,)):
        return None
    if isinstance(value, list):
        items = [value_item for value_item in value if value_item not in (None, "")]
        if field in {"tags", "genres", "actresses", "aliases"}:
            result: list[str] = []
            for item in items:
                result.extend(_split_list(str(item)))
            return result
        return _normalize_field(field, items[0], base_url, config) if items else None
    text = _clean_text(str(value))
    if not text:
        return None
    if field in {"tags", "genres", "actresses", "aliases"}:
        return _split_list(text)
    if field == "runtime_sec":
        return _parse_duration(text)
    if field in {"height_cm", "bust_cm", "waist_cm", "hips_cm", "year"}:
        return _parse_int(text)
    if field == "censored":
        return _normalize_censored(text)
    if field in {"release_date", "birth_date"}:
        return _normalize_date(text)
    if field == "cover_url":
        return _absolute_url(text, base_url, config)
    return text


def _split_list(value: str) -> list[str]:
    parts = re.split(r"[,，、\n|/]", value)
    return [part.strip() for part in parts if part.strip()]


def _parse_int(value: str) -> int | None:
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else None


def _parse_duration(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    if re.fullmatch(r"\d+", text):
        number = int(text)
        return number * 60 if number <= 600 else number
    match = re.search(r"(\d+)\s*(?:小时|時間|h)", text, re.IGNORECASE)
    hours = int(match.group(1)) if match else 0
    match = re.search(r"(\d+)\s*(?:分钟|分|min)", text, re.IGNORECASE)
    minutes = int(match.group(1)) if match else 0
    match = re.search(r"(\d+)\s*(?:秒|sec)", text, re.IGNORECASE)
    seconds = int(match.group(1)) if match else 0
    if hours or minutes or seconds:
        return hours * 3600 + minutes * 60 + seconds
    match = re.fullmatch(r"(\d+):(\d{1,2})(?::(\d{1,2}))?", text)
    if match:
        first, second, third = match.groups()
        if third is None:
            return int(first) * 60 + int(second)
        return int(first) * 3600 + int(second) * 60 + int(third)
    return _parse_int(text)


def _normalize_censored(value: str) -> str:
    text = value.lower()
    if any(token in text for token in ("无码", "無碼", "無修正", "uncensored", "流出")):
        return "uncensored"
    if any(token in text for token in ("有码", "有碼", "censored")):
        return "censored"
    return "unknown"


def _normalize_date(value: str) -> str:
    text = value.strip()
    match = re.search(r"((?:19|20)\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})", text)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    match = re.search(r"(?:19|20)\d{2}", text)
    return match.group(0) if match else text


def _absolute_url(value: str, base_url: str, config: dict[str, Any]) -> str:
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("//"):
        return "https:" + value
    asset_base = str(config.get("asset_base_url") or "")
    if asset_base and not value.startswith("/"):
        return urljoin(asset_base if asset_base.endswith("/") else asset_base + "/", value)
    return urljoin(base_url, value)


def _clean_text(value: Any) -> str:
    return html.unescape(str(value)).replace(" ", " ").strip()
