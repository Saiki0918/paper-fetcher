import logging
from typing import Any

import httpx

from app.core.http_client import request_json
from app.schemas.paper import Paper
from app.sources.base import PaperSourceError, access_priority, access_type
from app.utils.parsing import as_list, to_int
from app.utils.text import clean_text


class DblpError(PaperSourceError):
    """Raised when DBLP cannot return a usable search response."""


logger = logging.getLogger(__name__)


# 从 DBLP 作者字段中提取可展示的姓名列表。
def extract_authors(info: dict[str, Any]) -> list[str]:
    raw_authors = info.get("authors")
    raw_authors = raw_authors.get("author") if isinstance(raw_authors, dict) else raw_authors
    authors : list[str] = []
    for author in as_list(raw_authors):
        if isinstance(author, dict):
          row_name = author.get("#text") or author.get("text") or author.get("name")
        else:
            row_name = clean_text(author)

        name = clean_text(row_name)
        if name:
            authors.append(name)

    return authors
        



# 在 DBLP 的电子版本链接中查找直接 PDF 地址。
def extract_pdf_url(info: dict[str, Any]) -> str | None:
    for link in as_list(info.get("ee")):
        if isinstance(link, dict):
            link = link.get("#text") or link.get("url")
        if isinstance(link, str) and ".pdf" in link.lower():
            return link
    return None


class DblpAdapter:
    name = "DBLP"
    endpoint = "https://dblp.org/search/publ/api"

    # 请求 DBLP 搜索接口，并将返回记录规范化为 Paper。
    async def search(
        self,
        *,
        keyword: str,
        page: int,
        page_size: int,
    ) -> tuple[list[Paper], int]:
        params = {
            "q": keyword,
            "format": "json",
            "f": (page - 1) * page_size,
            "h": page_size,
        }
        try:
            payload = await request_json(self.endpoint, params=params)
        except (httpx.HTTPError, ValueError) as exc:
            logger.exception("DBLP 请求失败")
            raise DblpError(f"DBLP 请求失败: {exc}") from exc

        if not isinstance(payload, dict):
            logger.warning("DBLP 返回的 JSON 根节点不是对象")
            raise DblpError
        result = payload.get("result")
        hits = result.get("hits") if isinstance(result, dict) else None
        raw_hits = hits.get("hit") if isinstance(hits, dict) else None
        if raw_hits is None:
            logger.warning("DBLP 返回数据中缺少 result.hits.hit")
            raise DblpError

        total = to_int(hits.get("@total")) if isinstance(hits, dict) else 0
        papers = [self.to_paper(hit) for hit in as_list(raw_hits) if isinstance(hit, dict)]
        return sorted(papers, key=access_priority), total or 0

    @staticmethod
    # 从一条 DBLP 搜索命中记录中提取统一论文字段。
    def to_paper(hit: dict[str, Any]) -> Paper:
        info = hit.get("info")
        info = info if isinstance(info, dict) else {}
        doi = clean_text(info.get("doi"))
        url = clean_text(info.get("url")) or (f"https://doi.org/{doi}" if doi else "")
        identifier = clean_text(info.get("key")) or doi or url or "unknown"

        paper = Paper(
            id=f"dblp:{identifier}",
            platform="dblp",
            title=clean_text(info.get("title")) or "Untitled paper",
            year=to_int(info.get("year")),
            authors=extract_authors(info),
            abstract=None,
            source=clean_text(info.get("venue")) or "DBLP",
            doi=doi,
            url=url,
            citation_count=None,
            is_open_access=False,
            pdf_url=extract_pdf_url(info),
            access_type="detail",
        )
        return paper.model_copy(update={"access_type": access_type(paper)})
