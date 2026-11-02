"""演员名称的规范化与去重键生成。"""

from __future__ import annotations

import re
import unicodedata


def actress_name_key(name: str) -> str:
    """生成跨刮削源合并演员时使用的规范化键。"""
    # NFKC 合并全角/半角等兼容字符，casefold 做比 lower 更彻底的大小写折叠。
    value = unicodedata.normalize("NFKC", name).casefold()
    # 连续空白压成一个空格，避免仅因排版差异产生重复演员。
    value = re.sub(r"\s+", " ", value).strip()
    return value
