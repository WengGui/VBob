from __future__ import annotations

import re
import unicodedata


def actress_name_key(name: str) -> str:
    """Normalized key used to deduplicate actresses across sources."""
    value = unicodedata.normalize("NFKC", name).casefold()
    value = re.sub(r"\s+", " ", value).strip()
    return value
