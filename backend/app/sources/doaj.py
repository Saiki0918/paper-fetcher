import logging
from typing import Any
from urllib.parse import quote

import httpx

from app.core.http_client import request_json
from app.schemas.paper import Paper
from app.sources.base import PaperSourceError, access_priority, access_type
from app.utils.parsing import as_list, as_string, to_int


class DoajError(PaperSourceError):
    """Raised when DOAJ cannot return a usable search response."""


logger = logging.getLogger(__name__)


# 从 DOAJ 的 BibJSON 作者字段中提取姓名列表。
def extract_authors(bibjson: dict[str, Any]) -> list[str]:
    return [
        name
        for author in as_list(bibjson.get("author"))
        if isinstance(author, dict) and (name := as_string(author.get("name")))
    ]


# 从 DOAJ 的标识符列表中查找 DOI。
def extract_doi(bibjson: dict[str, Any]) -> str | None:
    for identifier in as_list(bibjson.get("identifier")):
        if isinstance(identifier, dict) and identifier.get("type") == "doi":
            return as_string(identifier.get("id"))
    return None


# 从 DOAJ 链接列表中分别找详情页和直接 PDF 地址。
def extract_links(bibjson: dict[str, Any]) -> tuple[str | None, str | None]:
    detail_url: str | None = None
    pdf_url: str | None = None
    for link in as_list(bibjson.get("link")):
        if not isinstance(link, dict):
            continue
        url = as_string(link.get("url"))
        if not url:
            continue
        if detail_url is None:
            detail_url = url
        content_type = as_string(link.get("content_type"))
        if content_type == "application/pdf" or ".pdf" in url.lower():
            pdf_url = url
    return detail_url, pdf_url


class DoajAdapter:
    name = "DOAJ"
    endpoint = "https://doaj.org/api/search/articles"

    # 请求 DOAJ 文章搜索接口，并将返回记录规范化为 Paper。
    async def search(
        self,
        *,
        keyword: str,
        page: int,
        page_size: int,
    ) -> tuple[list[Paper], int]:
        url = f"{self.endpoint}/{quote(keyword, safe='')}"
        try:
            payload = await request_json(url, params={"page": page, "pageSize": page_size})
        except (httpx.HTTPError, ValueError) as exc:
            logger.exception("DOAJ 请求失败")
            raise DoajError(f"DOAJ 请求失败: {exc}") from exc

        if not isinstance(payload, dict):
            logger.warning("DOAJ 返回的 JSON 根节点不是对象")
            raise DoajError
        results = payload.get("results")
        if not isinstance(results, list):
            logger.warning("DOAJ 返回数据中缺少 results 列表")
            raise DoajError

        papers = [self.to_paper(result) for result in results if isinstance(result, dict)]
        return sorted(papers, key=access_priority), to_int(payload.get("total")) or 0

    @staticmethod
    # 从一条 DOAJ 原始记录的 BibJSON 数据中提取统一论文字段。
    def to_paper(result: dict[str, Any]) -> Paper:
        bibjson = result.get("bibjson")
        bibjson = bibjson if isinstance(bibjson, dict) else {}
        journal = bibjson.get("journal")
        journal = journal if isinstance(journal, dict) else {}
        detail_url, pdf_url = extract_links(bibjson)
        doi = extract_doi(bibjson)
        record_id = as_string(result.get("id")) or as_string(result.get("_id")) or doi or "unknown"

        paper = Paper(
            id=f"doaj:{record_id}",
            platform="doaj",
            title=as_string(bibjson.get("title")) or "Untitled paper",
            year=to_int(bibjson.get("year")),
            authors=extract_authors(bibjson),
            abstract=as_string(bibjson.get("abstract")),
            source=as_string(journal.get("title")) or "DOAJ",
            doi=doi,
            url=detail_url or (f"https://doaj.org/article/{record_id}" if record_id != "unknown" else ""),
            citation_count=None,
            is_open_access=True,
            pdf_url=pdf_url,
            access_type="detail",
        )
        return paper.model_copy(update={"access_type": access_type(paper)})
