import logging
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.paper import Paper
from app.sources.base import PaperSourceError, access_priority, access_type
from app.utils.parsing import first_string
from app.utils.text import clean_text
from app.core.http_client import request_json


class CrossrefError(PaperSourceError):
    """Raised when Crossref cannot return a usable search response."""


logger = logging.getLogger(__name__)


# 按 Crossref 的多个日期字段顺序提取论文发表年份。
def extract_year(work: dict[str, Any]) -> int | None:
    for field in ("published-print", "published-online", "published", "issued", "created"):
        date = work.get(field)
        if not isinstance(date, dict):
            continue

        date_parts = date.get("date-parts")
        if not isinstance(date_parts, list) or not date_parts:
            continue

        first_part = date_parts[0]
        if isinstance(first_part, list) and first_part and isinstance(first_part[0], int):
            return first_part[0]
    return None


# 把 Crossref 作者对象列表转换为可展示的姓名列表。
def extract_authors(work: dict[str, Any]) -> list[str]:
    raw_authors = work.get("author")
    if not isinstance(raw_authors, list):
        return []

    authors: list[str] = []
    for raw_author in raw_authors:
        if not isinstance(raw_author, dict):
            continue

        name = " ".join(
            part
            for part in (raw_author.get("given"), raw_author.get("family"))
            if isinstance(part, str) and part
        )
        if name:
            authors.append(name)
    return authors


# 在 Crossref 附带链接中查找标记为 PDF 的直接地址。
def extract_pdf_url(work: dict[str, Any]) -> str | None:
    links = work.get("link")
    if not isinstance(links, list):
        return None

    for link in links:
        if not isinstance(link, dict):
            continue
        if link.get("content-type") == "application/pdf" and isinstance(link.get("URL"), str):
            return link["URL"]
    return None


class CrossrefAdapter:
    name = "Crossref"
    endpoint = "https://api.crossref.org/works"
    supported_types = {"journal-article", "proceedings-article", "posted-content"}

    # 请求 Crossref 搜索接口，并将返回记录规范化为 Paper。
    async def search(
        self,
        *,
        keyword: str,
        page: int,
        page_size: int,
    ) -> tuple[list[Paper], int]:
        params: dict[str, str | int] = {
            "query.bibliographic": keyword,
            "offset": (page - 1) * page_size,
            "rows": page_size,
            "filter": "type:journal-article",
        }
        if settings.crossref_mailto:
            params["mailto"] = settings.crossref_mailto

        try:
            payload = await request_json(
                self.endpoint,
                params=params,
                headers={
                    "User-Agent": f"PaperSearch/0.4 ({settings.crossref_mailto or 'local-development'})",
                },
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.exception("Crossref 请求失败")
            raise CrossrefError(f"Crossref 请求失败: {exc}") from exc

        if not isinstance(payload, dict):
            logger.warning("Crossref 返回的 JSON 根节点不是对象")
            raise CrossrefError

        message = payload.get("message")
        if not isinstance(message, dict):
            logger.warning("Crossref 返回数据中缺少 message 对象")
            raise CrossrefError

        items = message.get("items")
        if not isinstance(items, list):
            logger.warning("Crossref 返回数据中缺少 message.items 列表")
            raise CrossrefError

        total = message.get("total-results", 0)
        if not isinstance(total, int):
            total = 0

        papers = [
            self.to_paper(work)
            for work in items
            if isinstance(work, dict) and work.get("type") in self.supported_types
        ]
        return sorted(papers, key=access_priority), total

    @staticmethod
    # 从一条 Crossref 原始 work 记录中提取统一论文字段。
    def to_paper(work: dict[str, Any]) -> Paper:
        resource = work.get("resource") or {}
        primary_resource = resource.get("primary") if isinstance(resource, dict) else {}
        if not isinstance(primary_resource, dict):
            primary_resource = {}

        doi = work.get("DOI") if isinstance(work.get("DOI"), str) else None
        url = primary_resource.get("URL") or work.get("URL") or (f"https://doi.org/{doi}" if doi else "")

        paper = Paper(
            id=f"crossref:{doi or url}",
            platform="crossref",
            title=first_string(work.get("title")) or "Untitled paper",
            year=extract_year(work),
            authors=extract_authors(work),
            abstract=clean_text(work.get("abstract")),
            source=first_string(work.get("container-title")) or work.get("publisher"),
            doi=doi,
            url=url,
            citation_count=work.get("is-referenced-by-count"),
            is_open_access=False,
            pdf_url=extract_pdf_url(work),
            access_type="detail",
        )
        return paper.model_copy(update={"access_type": access_type(paper)})
