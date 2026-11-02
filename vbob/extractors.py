"""文件名特征提取：清洗噪声后识别番号，并推断标题与年份。

关键流程：
- clean_noise 先做 NFKC 归一化，再用可配置规则删除画质/站点/字幕等噪声；
- 番号识别按 FC2 > HEYZO > 无码 > 标准番号 的优先级取第一个命中；
- TitleYearExtractor 先移除番号再取年份，避免番号中的数字被误判为年份。

各提取器彼此独立，单个提取器异常不会影响其他提取器。
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Protocol

log = logging.getLogger(__name__)

# 默认清洗规则：方括号内容、画质/编码/字幕标记、站点域名与结尾标识。
DEFAULT_CLEAN_RULES: tuple[str, ...] = (
    r"\[[^\]]*\]",
    r"【[^】]*】",
    r"(?i)\((?:\s*(?:1080p|720p|2160p|480p|4k|8k|uhd|hdr|hevc|avc|h\.?264|h\.?265|"
    r"x264|x265|aac|ac3|dts|web[-_. ]?dl|blu[-_. ]?ray|bdrip|hdrip|dvdrip|"
    r"中字|中文字幕|无码|無碼|uncensored)\s*)\)",
    r"(?i)\b(?:1080p|720p|2160p|480p|4k|8k|uhd|hdr10?|dolby[ .]?vision|hevc|avc|"
    r"h\.?264|h\.?265|x264|x265|aac|ac3|dts|flac|web[-_. ]?dl|blu[-_. ]?ray|"
    r"bdrip|hdrip|dvdrip|remux)\b",
    r"(?i)\b(?:www\.)?[a-z0-9][a-z0-9-]*\.(?:com|net|org|cc|tv|xyz|me|info|top|club|vip|la)\b",
    r"(?i)[-_. ](?:c|chs|cht|uncensored)$",
)

# 标准番号匹配时排除这些常见技术/分卷词，避免把 "CD-2" 之类误识别为番号。
CODE_STOPWORDS = {
    "PART", "CD", "DISC", "DISK", "VOL", "VOLUME", "EP", "EPISODE", "SEASON",
    "WEB", "BD", "DVD", "HD", "FHD", "UHD", "AAC", "DTS", "HEVC", "AVC",
    "REMUX", "SP", "OVA", "MOVIE",
}

# FC2 番号，可选 PPV 前缀；HEYZO 为 3-4 位数字。
_FC2_RE = re.compile(r"(?i)(?<![A-Z0-9])FC2[-_ ]?(PPV[-_ ]?)?(\d{6,8})(?![0-9])")
_HEYZO_RE = re.compile(r"(?i)(?<![A-Z0-9])HEYZO[-_ ]?(\d{3,4})(?![0-9])")
# 无码番号形如 123456-789；标准番号为字母前缀 + 数字。
_UNCENSORED_RE = re.compile(r"(?<!\d)(\d{6})-(\d{3})(?!\d)")
_STANDARD_RE = re.compile(r"(?i)(?<![A-Z0-9])([A-Z]{2,6})-(\d{2,5})(?![A-Z0-9])")
# 四位年份，前后加边界避免匹配到更长数字的一部分。
_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_CODE_RES = (_FC2_RE, _HEYZO_RE, _UNCENSORED_RE, _STANDARD_RE)


@dataclass(frozen=True)
class FileRef:
    """待提取的单个文件信息；dirs 为从近到远的父目录名。"""

    filename: str
    rel_path: str = ""
    dirs: tuple[str, ...] = ()


@dataclass(frozen=True)
class CodeMatch:
    """一次番号匹配结果；match_key 用于跨文件去重与关联。"""

    code: str
    family: str
    match_key: str
    start: int
    end: int


class FeatureExtractor(Protocol):
    """提取器协议：name 用于日志，extract 返回要合并进特征字典的字段。"""

    name: str

    def extract(self, file: FileRef) -> dict[str, object]: ...


def _stem(filename: str) -> str:
    """取文件名（不含扩展名）。"""
    return os.path.splitext(filename)[0]


def _compile_rules(extra: Iterable[str] = ()) -> tuple[re.Pattern[str], ...]:
    """合并默认清洗规则与用户自定义规则并编译。"""
    patterns = list(DEFAULT_CLEAN_RULES) + [rule for rule in extra if rule.strip()]
    return tuple(re.compile(pattern) for pattern in patterns)


def clean_noise(text: str, patterns: tuple[re.Pattern[str], ...]) -> str:
    """NFKC 归一化后依次应用规则；噪声替换为空格可避免相邻词粘连。"""
    text = unicodedata.normalize("NFKC", text)
    for pattern in patterns:
        text = pattern.sub(" ", text)
    return text


def _match_code(text: str) -> CodeMatch | None:
    """按类型优先级返回第一个命中的番号（FC2 > HEYZO > 无码 > 标准）。"""
    match = _FC2_RE.search(text)
    if match:
        ppv = bool(match.group(1))
        digits = match.group(2)
        code = f"FC2-PPV-{digits}" if ppv else f"FC2-{digits}"
        return CodeMatch(code, "fc2", f"fc2|{int(digits)}", match.start(), match.end())

    match = _HEYZO_RE.search(text)
    if match:
        digits = match.group(1)
        return CodeMatch(
            f"HEYZO-{digits}", "heyzo", f"heyzo|{int(digits)}", match.start(), match.end()
        )

    match = _UNCENSORED_RE.search(text)
    if match:
        prefix, suffix = match.group(1), match.group(2)
        return CodeMatch(
            f"{prefix}-{suffix}",
            "uncensored",
            f"uncen|{int(prefix)}|{int(suffix)}",
            match.start(),
            match.end(),
        )

    for match in _STANDARD_RE.finditer(text):
        label = match.group(1).upper()
        if label in CODE_STOPWORDS:
            continue
        digits = match.group(2)
        return CodeMatch(
            f"{label}-{digits}",
            "standard",
            f"{label}|{int(digits)}",
            match.start(),
            match.end(),
        )
    return None


class JavCodeExtractor:
    """从文件名及父目录中识别番号。"""

    name = "jav_code"

    def __init__(self, extra_clean_rules: Iterable[str] = ()) -> None:
        self._patterns = _compile_rules(extra_clean_rules)

    def extract(self, file: FileRef) -> dict[str, object]:
        """依次尝试文件名和父目录，返回番号、类型与匹配键。"""
        stem = _stem(file.filename)
        # 文件名最可靠；失败时再按从近到远的顺序查找父目录。
        candidates = [stem, *file.dirs]
        for candidate in candidates:
            cleaned = clean_noise(candidate, self._patterns)
            match = _match_code(cleaned)
            if match:
                return {
                    "jav_code": match.code,
                    "jav_family": match.family,
                    "jav_match_key": match.match_key,
                }
        return {}


class TitleYearExtractor:
    """从文件名推断标题和年份；推断前会先移除番号片段。"""

    name = "title_year"

    def __init__(self, extra_clean_rules: Iterable[str] = ()) -> None:
        self._patterns = _compile_rules(extra_clean_rules)

    def extract(self, file: FileRef) -> dict[str, object]:
        """返回 {"title", "year"} 中能够确定的字段。"""
        stem = _stem(file.filename)
        text = clean_noise(stem, self._patterns)

        # 去掉番号片段，避免其中的数字被年份正则误判。
        for pattern in _CODE_RES:
            text = pattern.sub(" ", text)

        year = self._extract_year(text)
        if year is not None:
            # 年份已取到，再从文本中删除，防止残留在标题里。
            text = re.sub(rf"(?<!\d){year}(?!\d)", " ", text)

        title = self._clean_title(text)
        result: dict[str, object] = {}
        if title:
            result["title"] = title
        if year is not None:
            result["year"] = year
        return result

    @staticmethod
    def _extract_year(text: str) -> int | None:
        """取最后一个合法年份，通常上映年份更靠近文件名末尾。"""
        max_year = datetime.now().year + 2
        found: int | None = None
        for match in _YEAR_RE.finditer(text):
            value = int(match.group(1))
            if 1950 <= value <= max_year:
                found = value
        return found

    @staticmethod
    def _clean_title(text: str) -> str | None:
        """把残留分隔符折叠为空格并去掉首尾符号；无字母数字则视为空标题。"""
        text = re.sub(r"[._\-]+", " ", text)
        text = re.sub(r"\s+", " ", text)
        text = text.strip(" \t\r\n-_[](){}<>|,;:+*\"'")
        if not any(ch.isalnum() for ch in text):
            return None
        return text


_CHINESE_NUMERALS = "零〇一二三四五六七八九十百两"
_CHINESE_EPISODE_RE = re.compile(
    rf"第\s*([{_CHINESE_NUMERALS}]+)\s*[集话話期季]"
)
_EXPLICIT_EPISODE_PATTERNS = (
    # 第3集 / 第三集 / 第 3 話；也接受“第 1 季第 3 集”中的多个标记。
    _CHINESE_EPISODE_RE,
    re.compile(r"第\s*(\d{1,4})\s*[集话話期季]"),
    # 03集 / 03話，数字前不能紧贴其他数字。
    re.compile(r"(?<!\d)(\d{1,3})\s*[集话話](?!\d)"),
    # Episode 3 / EP03 / EP.03
    re.compile(r"(?i)\b(?:episode|ep)\s*[._\- ]?\s*(\d{1,4})\b"),
    # S01E03
    re.compile(r"(?i)\bs(\d{1,2})\s*e(\d{1,3})\b"),
)
# 结尾数字 1-3 位；避免把 4 位年份或长数字（如手机拍摄文件名）当成集数。
_TRAILING_EPISODE_RE = re.compile(r"^(.*?)(?<!\d)(\d{1,3})$")
# 常见分辨率数字，文件名以它们结尾时不应视为集数。
_NOT_EPISODE_NUMBERS = {360, 480, 540, 576, 720, 1080, 2160}


def _chinese_number(text: str) -> int | None:
    """把“十二”“一百零二”等中文数字转换为整数；无法解析时返回 None。"""
    digits = {
        "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
        "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    }
    units = {"十": 10, "百": 100}
    total = 0
    current = 0
    for char in text:
        if char in digits:
            current = digits[char]
        elif char in units:
            total += (current or 1) * units[char]
            current = 0
        else:
            return None
    value = total + current
    return value or None


def _normalize_group_text(text: str) -> str:
    """归一化标题用于分组比较：去掉年份括号、空白与常见分隔符。"""
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"[\(\[（【]\s*(?:19|20)\d{2}\s*[\)\]）】]", " ", text)
    return re.sub(r"[\s._\-·:：]+", "", text)


class EpisodeExtractor:
    """识别剧集文件，并从文件名/所在文件夹推断剧集标题与分组键。

    支持“第3集”“EP03”“S01E03”和“标题3”等命名；当文件名本身只是集数时，
    使用最近一级文件夹名作为标题。输出 ``episode_key`` 供扫描器合并同一剧集的
    多个文件，只会显示一张海报并只刮削一次。
    """

    name = "episode"

    def __init__(self, extra_clean_rules: Iterable[str] = ()) -> None:
        self._patterns = _compile_rules(extra_clean_rules)

    def extract(self, file: FileRef) -> dict[str, object]:
        stem = _stem(file.filename)
        cleaned = clean_noise(stem, self._patterns)
        folder = clean_noise(file.dirs[0], self._patterns) if file.dirs else ""

        # 1) 显式集数标记：标记可以出现在标题前后，移除后得到剧集标题。
        explicit = False
        episode: str | int | None = None
        for pattern in _EXPLICIT_EPISODE_PATTERNS:
            matches = list(pattern.finditer(cleaned))
            if not matches:
                continue
            explicit = True
            last = matches[-1]
            if pattern is _CHINESE_EPISODE_RE:
                episode = _chinese_number(last.group(1))
            elif pattern.pattern.startswith("(?i)\\bs"):
                episode = f"S{int(last.group(1)):02d}E{int(last.group(2)):02d}"
            else:
                episode = int(last.group(1))
            cleaned = pattern.sub(" ", cleaned)

        base = TitleYearExtractor._clean_title(cleaned) or ""

        # 2) 结尾数字：只有标题与文件夹同名时才视为集数，避免把“Toy Story 2”
        #    这类独立续集误合并；纯数字文件名则直接使用文件夹标题。
        if not explicit:
            match = _TRAILING_EPISODE_RE.match(cleaned)
            if match:
                number = int(match.group(2))
                trailing_base = TitleYearExtractor._clean_title(match.group(1)) or ""
                folder_norm = _normalize_group_text(folder)
                base_norm = _normalize_group_text(trailing_base)
                # 同名（光与影的传说3）或以文件夹名开头（光与影的传说外传1）
                # 才按剧集分组；独立的“Toy Story 2”不会因为结尾数字被误合并。
                same_series = bool(base_norm and folder_norm) and (
                    base_norm == folder_norm or base_norm.startswith(folder_norm)
                )
                if not trailing_base and folder_norm:
                    base = folder
                    episode = number
                elif same_series and number not in _NOT_EPISODE_NUMBERS:
                    base = trailing_base
                    episode = number

        if not explicit and episode is None:
            return {}

        # 3) 标题优先使用去掉集数后的片名；只有集数时退回文件夹名。
        title = base or folder
        group_text = title if title else ""
        group_norm = _normalize_group_text(group_text)
        if not group_norm:
            return {}
        parent = os.path.dirname(file.rel_path).replace("\\", "/").casefold()
        return {
            "title": group_text,
            "episode": episode,
            "is_episode": True,
            "episode_key": f"episode|{parent}|{group_norm}",
        }


class FeaturePipeline:
    """按顺序运行所有提取器并合并结果。"""

    def __init__(self, extra_clean_rules: Iterable[str] = ()) -> None:
        rules = tuple(extra_clean_rules)
        self._extractors: tuple[FeatureExtractor, ...] = (
            JavCodeExtractor(rules),
            TitleYearExtractor(rules),
            EpisodeExtractor(rules),
        )

    def extract(self, file: FileRef) -> dict[str, object]:
        """执行全部提取器并返回合并后的特征字典。"""
        features: dict[str, object] = {}
        for extractor in self._extractors:
            try:
                result = extractor.extract(file)
                # 已识别出 JAV 番号时优先按番号分组，避免“CD1”等分卷名覆盖标题。
                if extractor.name == "episode" and "jav_match_key" in features:
                    continue
                features.update(result)
            except Exception:  # noqa: BLE001 - a broken extractor must not block the scan
                # 单个提取器异常只记录日志，不能中断整个扫描。
                log.exception("extractor %s failed for %s", extractor.name, file.filename)
        return features
