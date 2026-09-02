import logging
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.paper import Paper
from app.sources.base import PaperSourceError, access_priority, access_type
from app.core.http_client import request_json
from app.utils.parsing import as_string, to_int
from app.utils.text import clean_text


class EuropePmcError(PaperSourceError):
    """Raised when Europe PMC cannot return a usable search response."""


logger = logging.getLogger(__name__)

# 从 Europe PMC 的作者结构或作者文本中提取姓名列表。
def extract_authors(result: dict[str, Any]) -> list[str]:
    author_list = result.get("authorList")
    if isinstance(author_list, dict):
        authors = author_list.get("author")
        if isinstance(authors, dict):
            authors = [authors]
        if isinstance(authors, list):
            names = [
                author.get("fullName")
                for author in authors
                if isinstance(author, dict) and isinstance(author.get("fullName"), str)
            ]
            if names:
                return names

    author_string = as_string(result.get("authorString"))
    return [name.strip() for name in author_string.split(",") if name.strip()] if author_string else []


# 从全文链接中找 PDF，或为确认有 PDF 的 PMC 记录构造地址。
def extract_pdf_url(result: dict[str, Any]) -> str | None:
    url_list = result.get("fullTextUrlList")
    urls = url_list.get("fullTextUrl") if isinstance(url_list, dict) else None
    if isinstance(urls, dict):
        urls = [urls]
    if isinstance(urls, list):
        for link in urls:
            if not isinstance(link, dict):
                continue
            url = as_string(link.get("url"))
            mime_type = as_string(link.get("mimeType"))
            if url and (mime_type == "application/pdf" or ".pdf" in url.lower()):
                return url

    pmcid = as_string(result.get("pmcid"))
    has_pdf = result.get("hasPDF") == "Y"
    if pmcid and has_pdf:
        return f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/pdf/"
    return None


class EuropePmcAdapter:
    name = "Europe PMC"
    endpoint = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    # 请求 Europe PMC 搜索接口，并将 JSON 结果规范化为 Paper。
    async def search(
        self,
        *,
        keyword: str,
        page: int,
        page_size: int,
    ) -> tuple[list[Paper], int]:
        params = {
            "query": keyword,
            "format": "json",
            "resultType": "core",
            "page": page,
            "pageSize": page_size,
        }
        try:
            payload = await request_json(
                self.endpoint,
                params=params,
                timeout=settings.europepmc_timeout_seconds,
            )
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            logger.exception("Europe PMC 返回 HTTP %s", status_code)
            raise EuropePmcError(f"Europe PMC 返回 HTTP {status_code}") from exc
        except httpx.TimeoutException as exc:
            logger.exception("Europe PMC 请求在 %s 秒后超时", settings.europepmc_timeout_seconds)
            raise EuropePmcError("Europe PMC 请求超时，请稍后重试") from exc
        except httpx.RequestError as exc:
            logger.exception("Europe PMC 网络请求失败")
            raise EuropePmcError("Europe PMC 网络请求失败，请稍后重试") from exc
        except ValueError as exc:
            logger.exception("Europe PMC 返回无法解析的 JSON")
            raise EuropePmcError("Europe PMC 返回的数据格式无法解析") from exc

        if not isinstance(payload, dict):
            raise EuropePmcError

        result_list = payload.get("resultList")
        results = result_list.get("result") if isinstance(result_list, dict) else None
        if not isinstance(results, list):
            logger.warning("Europe PMC 返回数据中缺少 resultList.result 列表")
            raise EuropePmcError("Europe PMC 返回的数据中没有论文列表")

        total = to_int(payload.get("hitCount")) or 0
        papers = [self.to_paper(result) for result in results if isinstance(result, dict)]
        return sorted(papers, key=access_priority), total

    @staticmethod
    # 从一条 Europe PMC 原始记录中提取统一论文字段。
    def to_paper(result: dict[str, Any]) -> Paper:
        source_code = as_string(result.get("source")) or "MED"
        record_id = as_string(result.get("id")) or "unknown"
        journal_info = result.get("journalInfo")
        journal = journal_info.get("journal") if isinstance(journal_info, dict) else None
        journal_title = journal.get("title") if isinstance(journal, dict) else None
        source = as_string(journal_title) or as_string(result.get("journalTitle")) or source_code
        is_open_access = result.get("isOpenAccess") == "Y"

        paper = Paper(
            id=f"europepmc:{source_code}:{record_id}",
            platform="europepmc",
            title=as_string(result.get("title")) or "Untitled paper",
            year=to_int(result.get("pubYear")),
            authors=extract_authors(result),
            abstract=clean_text(result.get("abstractText")),
            source=source,
            doi=as_string(result.get("doi")),
            url=f"https://europepmc.org/article/{source_code}/{record_id}",
            citation_count=to_int(result.get("citedByCount")),
            is_open_access=is_open_access,
            pdf_url=extract_pdf_url(result),
            access_type="detail",
        )
        return paper.model_copy(update={"access_type": access_type(paper)})
