"""提供 XML 节点文本提取工具。"""

from xml.etree import ElementTree


# 提取 XML 元素及其嵌套节点的完整文字并压缩空白。
def xml_text(element: ElementTree.Element | None) -> str | None:
    """Return normalized text from an XML element or None when absent."""
    if element is None:
        return None

    value = " ".join("".join(element.itertext()).split())
    return value or None

