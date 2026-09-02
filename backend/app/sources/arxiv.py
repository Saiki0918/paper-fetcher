import logging
from typing import Final
from xml.etree import ElementTree

import httpx

from app.core.http_client import request_content
from app.schemas.paper import Paper
from app.sources.base import PaperSourceError, access_priority, access_type
from app.utils.xml import xml_text


class ArxivError(PaperSourceError):
    """Raised when arXiv cannot return a usable search response."""


logger = logging.getLogger(__name__)


ATOM_NAMESPACE: Final = "http://www.w3.org/2005/Atom"
ARXIV_NAMESPACE: Final = "http://arxiv.org/schemas/atom"
OPENSEARCH_NAMESPACE: Final = "http://a9.com/-/spec/opensearch/1.1/"
NAMESPACES: Final = {
    "atom": ATOM_NAMESPACE,
    "arxiv": ARXIV_NAMESPACE,
    "opensearch": OPENSEARCH_NAMESPACE,
}


# 从 arXiv 的日期文本中读取四位年份。
def parse_year(value: str | None) -> int | None:
    if not value or len(value) < 4:
        return None
    try:
        return int(value[:4])
    except ValueError:
        return None


class ArxivAdapter:
    name = "arXiv"
    endpoint = "https://export.arxiv.org/api/query"

    # 请求 arXiv Atom 接口，解析 XML 并返回统一的论文列表。
    async def search(
        self,
        *,
        keyword: str,
        page: int,
        page_size: int,
    ) -> tuple[list[Paper], int]:
        params = {
            "search_query": f'all:"{keyword}"',
            "start": (page - 1) * page_size,
            "max_results": page_size,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        try:
            content = await request_content(
                self.endpoint,
                params=params,
                headers={"Accept": "application/atom+xml"},
            )
            root = ElementTree.fromstring(content)
        except (httpx.HTTPError, ElementTree.ParseError) as exc:
            logger.exception("arXiv 请求或 XML 解析失败")
            raise ArxivError(f"arXiv 请求或 XML 解析失败: {exc}") from exc

        total_text = root.findtext("opensearch:totalResults", namespaces=NAMESPACES)
        try:
            total = int(total_text or 0)
        except ValueError:
            total = 0

        papers = [
            self.to_paper(entry)
            for entry in root.findall("atom:entry", NAMESPACES)
        ]
        return sorted(papers, key=access_priority), total

    @staticmethod
    # 从一条 arXiv Atom entry 元素中提取统一论文字段。
    def to_paper(entry: ElementTree.Element) -> Paper:
        detail_url = xml_text(entry.find("atom:id", NAMESPACES)) or ""
        pdf_url: str | None = None
        for link in entry.findall("atom:link", NAMESPACES):
            href = link.get("href")
            if not href:
                continue
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf_url = href
            elif link.get("rel") == "alternate":
                detail_url = href

        authors = [
            name
            for author in entry.findall("atom:author", NAMESPACES)
            if (name := xml_text(author.find("atom:name", NAMESPACES)))
        ]
        category = entry.find("arxiv:primary_category", NAMESPACES)
        category_name = category.get("term") if category is not None else None
        arxiv_id = detail_url.rstrip("/").split("/")[-1] or "unknown"
        doi = xml_text(entry.find("arxiv:doi", NAMESPACES))

        paper = Paper(
            id=f"arxiv:{arxiv_id}",
            platform="arxiv",
            title=xml_text(entry.find("atom:title", NAMESPACES)) or "Untitled paper",
            year=parse_year(xml_text(entry.find("atom:published", NAMESPACES))),
            authors=authors,
            abstract=xml_text(entry.find("atom:summary", NAMESPACES)),
            source=f"arXiv{f' · {category_name}' if category_name else ''}",
            doi=doi,
            url=detail_url,
            citation_count=None,
            is_open_access=True,
            pdf_url=pdf_url,
            access_type="detail",
        )
        return paper.model_copy(update={"access_type": access_type(paper)})
