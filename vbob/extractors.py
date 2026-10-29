from __future__ import annotations

import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Protocol

log = logging.getLogger(__name__)

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

CODE_STOPWORDS = {
    "PART", "CD", "DISC", "DISK", "VOL", "VOLUME", "EP", "EPISODE", "SEASON",
    "WEB", "BD", "DVD", "HD", "FHD", "UHD", "AAC", "DTS", "HEVC", "AVC",
    "REMUX", "SP", "OVA", "MOVIE",
}

_FC2_RE = re.compile(r"(?i)(?<![A-Z0-9])FC2[-_ ]?(PPV[-_ ]?)?(\d{6,8})(?![0-9])")
_HEYZO_RE = re.compile(r"(?i)(?<![A-Z0-9])HEYZO[-_ ]?(\d{3,4})(?![0-9])")
_UNCENSORED_RE = re.compile(r"(?<!\d)(\d{6})-(\d{3})(?!\d)")
_STANDARD_RE = re.compile(r"(?i)(?<![A-Z0-9])([A-Z]{2,6})-(\d{2,5})(?![A-Z0-9])")
_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_CODE_RES = (_FC2_RE, _HEYZO_RE, _UNCENSORED_RE, _STANDARD_RE)


@dataclass(frozen=True)
class FileRef:
    filename: str
    rel_path: str = ""
    dirs: tuple[str, ...] = ()


@dataclass(frozen=True)
class CodeMatch:
    code: str
    family: str
    match_key: str
    start: int
    end: int


class FeatureExtractor(Protocol):
    name: str

    def extract(self, file: FileRef) -> dict[str, object]: ...


def _stem(filename: str) -> str:
    return os.path.splitext(filename)[0]


def _compile_rules(extra: Iterable[str] = ()) -> tuple[re.Pattern[str], ...]:
    patterns = list(DEFAULT_CLEAN_RULES) + [rule for rule in extra if rule.strip()]
    return tuple(re.compile(pattern) for pattern in patterns)


def clean_noise(text: str, patterns: tuple[re.Pattern[str], ...]) -> str:
    text = unicodedata.normalize("NFKC", text)
    for pattern in patterns:
        text = pattern.sub(" ", text)
    return text


def _match_code(text: str) -> CodeMatch | None:
    """Return the first code in family priority order (FC2 > HEYZO > uncensored > standard)."""
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
    name = "jav_code"

    def __init__(self, extra_clean_rules: Iterable[str] = ()) -> None:
        self._patterns = _compile_rules(extra_clean_rules)

    def extract(self, file: FileRef) -> dict[str, object]:
        stem = _stem(file.filename)
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
    name = "title_year"

    def __init__(self, extra_clean_rules: Iterable[str] = ()) -> None:
        self._patterns = _compile_rules(extra_clean_rules)

    def extract(self, file: FileRef) -> dict[str, object]:
        stem = _stem(file.filename)
        text = clean_noise(stem, self._patterns)

        # Remove code spans so their digits are not mistaken for a year.
        for pattern in _CODE_RES:
            text = pattern.sub(" ", text)

        year = self._extract_year(text)
        if year is not None:
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
        max_year = datetime.now().year + 2
        found: int | None = None
        for match in _YEAR_RE.finditer(text):
            value = int(match.group(1))
            if 1950 <= value <= max_year:
                found = value
        return found

    @staticmethod
    def _clean_title(text: str) -> str | None:
        text = re.sub(r"[._\-]+", " ", text)
        text = re.sub(r"\s+", " ", text)
        text = text.strip(" \t\r\n-_[](){}<>|,;:+*\"'")
        if not any(ch.isalnum() for ch in text):
            return None
        return text


class FeaturePipeline:
    """Runs all extractors and merges their output."""

    def __init__(self, extra_clean_rules: Iterable[str] = ()) -> None:
        rules = tuple(extra_clean_rules)
        self._extractors: tuple[FeatureExtractor, ...] = (
            JavCodeExtractor(rules),
            TitleYearExtractor(rules),
        )

    def extract(self, file: FileRef) -> dict[str, object]:
        features: dict[str, object] = {}
        for extractor in self._extractors:
            try:
                features.update(extractor.extract(file))
            except Exception:  # noqa: BLE001 - a broken extractor must not block the scan
                log.exception("extractor %s failed for %s", extractor.name, file.filename)
        return features
