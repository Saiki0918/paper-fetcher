"""提供对不同平台返回的 JSON 值进行安全规范化的函数。"""

from typing import Any


# 将单个值、列表或空值统一转换成便于遍历的列表。
def as_list(value: Any) -> list[Any]:
    """Return a list without changing an existing list value."""
    return value if isinstance(value, list) else [value] if value is not None else []


# 仅接受非空字符串，避免适配器直接处理不稳定的第三方字段类型。
def as_string(value: Any) -> str | None:
    """Return non-empty strings and convert all other values to None."""
    return value if isinstance(value, str) and value else None


# 将整数或纯数字字符串安全地转换为整数。
def to_int(value: Any) -> int | None:
    """Convert an integer-like value to int, returning None when invalid."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


# 从字符串或字符串列表中取出第一个有效文本值。
def first_string(value: Any) -> str | None:
    """Return the first non-empty string from a scalar or list."""
    if isinstance(value, list):
        return next((item for item in (as_string(item) for item in value) if item), None)
    return as_string(value)
