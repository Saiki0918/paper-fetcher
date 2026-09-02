"""提供跨平台通用的文本清理函数。"""

import html
import re
from typing import Any


# 移除 HTML 标签、还原实体字符并压缩多余空白。
def clean_text(value: Any) -> str | None:
    """Normalize HTML or plain text returned by an academic API."""
    if not isinstance(value, str) or not value:
        return None

    text = html.unescape(re.sub(r"<[^>]*>", " ", value))
    return " ".join(text.split()) or None

