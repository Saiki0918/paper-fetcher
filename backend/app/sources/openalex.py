from typing import Any

import httpx

from app.core.config import settings
from app.schemas.paper import Paper
from app.sources.base import PaperSourceError, access_priority, access_type


class OpenAlexError(PaperSourceError):
    """Raised when OpenAlex cannot return a usable search response."""


# 将 OpenAlex 倒排索引格式的摘要还原为按原顺序排列的文本。
def reconstruct_abstract(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None

    words: list[tuple[int, str]] = []
    for word, positions in index.items():
        words.extend((position, word) for position in positions)

    if not words:
        return None

    words.sort(key=lambda item: item[0])
    return " ".join(word for _, word in words)


class OpenAlexAdapter:
    name = "OpenAlex"
    endpoint = "https://api.openalex.org/works"

    # 请求 OpenAlex 搜索接口，并将返回记录规范化为 Paper。
    async def search(
        self,
        *,
        keyword: str,
        page: int,
        page_size: int,
    ) -> tuple[list[Paper], int]:
        params: dict[str, str | int] = {
            "search": keyword,
            "page": page,
            "per-page": page_size,
        }
        if settings.openalex_mailto:
            params["mailto"] = settings.openalex_mailto
        if settings.openalex_api_key:
            params["api_key"] = settings.openalex_api_key

        headers = {
            "Accept": "application/json",
            "User-Agent": f"PaperSearch/0.1 ({settings.openalex_mailto or 'local-development'})",
        }

        try:
            async with httpx.AsyncClient(
                timeout=settings.http_timeout_seconds,
                headers=headers,
            ) as client:
                response = await client.get(self.endpoint, params=params)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OpenAlexError from exc

        if not isinstance(payload, dict):
            raise OpenAlexError

        results = payload.get("results")
        if not isinstance(results, list):
            raise OpenAlexError

        meta = payload.get("meta") or {}
        total = meta.get("count", 0)
        if not isinstance(total, int):
            total = 0

        papers = [self.to_paper(work) for work in results if isinstance(work, dict)]
        return sorted(papers, key=access_priority), total

    @staticmethod
    # 从一条 OpenAlex 原始 work 记录中提取统一论文字段。
    def to_paper(work: dict[str, Any]) -> Paper:
        primary_location = work.get("primary_location") or {}
        best_location = work.get("best_oa_location") or primary_location
        primary_source = primary_location.get("source") or {}
        best_source = best_location.get("source") or {}

        source = (
            primary_source.get("display_name")
            or primary_location.get("raw_source_name")
            or best_source.get("display_name")
            or best_location.get("raw_source_name")
        )
        url = (
            best_location.get("landing_page_url")
            or primary_location.get("landing_page_url")
            or work.get("doi")
            or work.get("id")
            or ""
        )

        authors = [
            author.get("display_name")
            for authorship in work.get("authorships", [])
            if isinstance(authorship, dict)
            for author in [authorship.get("author") or {}]
            if author.get("display_name")
        ]

        paper = Paper(
            id=f"openalex:{work.get('id', '')}",
            platform="openalex",
            title=work.get("display_name") or work.get("title") or "Untitled paper",
            year=work.get("publication_year"),
            authors=authors,
            abstract=reconstruct_abstract(work.get("abstract_inverted_index")),
            source=source,
            doi=work.get("doi"),
            url=url,
            citation_count=work.get("cited_by_count"),
            download_count=None,
            is_open_access=bool((work.get("open_access") or {}).get("is_oa")),
            pdf_url=best_location.get("pdf_url"),
            access_type="detail",
        )
        return paper.model_copy(update={"access_type": access_type(paper)})
