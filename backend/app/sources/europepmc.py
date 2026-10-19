"""Europe PMC 通用检索与字段解析，供总入口和按发布者筛选的预印本入口共用。"""

import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.config import settings
from app.schemas.paper import Paper
from app.sources.base import PaperSourceError, access_priority, access_type
from app.sources.preprint_pdf import PreprintPdfEnricher, chemrxiv_pdf_url
from app.core.http_client import request_json
from app.utils.parsing import as_list, as_string, to_int
from app.utils.text import clean_text


class EuropePmcError(PaperSourceError):
    """Europe PMC 请求失败或未返回可用的搜索响应。"""


logger = logging.getLogger(__name__)

# 从 Europe PMC 的作者结构或作者文本中提取姓名列表。
def extract_authors(result: dict[str, Any]) -> list[str]:
    author_list = result.get("authorList")
    if isinstance(author_list, dict):
        authors = author_list.get("author")
        if isinstance(authors, dict):
            authors = [authors]
        if isinstance(authors, list):
            # 团体作者使用 collectiveName，不能只读取个人作者的 fullName。
            names = [
                author.get("fullName") or author.get("collectiveName")
                for author in authors
                if isinstance(author, dict)
                and isinstance(author.get("fullName") or author.get("collectiveName"), str)
            ]
            if names:
                return names

    # 缺少结构化作者时再使用文本字段，避免同时读取两套字段造成重复署名。
    author_string = as_string(result.get("authorString"))
    return [name.strip() for name in author_string.split(",") if name.strip()] if author_string else []


# 全文链接可能是单个对象、数组或空值，统一处理后供访问状态和 PDF 解析共用。
def full_text_links(result: dict[str, Any]) -> list[dict[str, Any]]:
    url_list = result.get("fullTextUrlList")
    urls = url_list.get("fullTextUrl") if isinstance(url_list, dict) else None
    return [link for link in as_list(urls) if isinstance(link, dict)]


# fulltextRepo 是 Europe PMC 的文件代理，搜索 API 返回的地址可能已失效。
def is_epmc_file_proxy(url: str) -> bool:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return (
        parsed.hostname in {"europepmc.org", "www.europepmc.org"}
        and parsed.path.rstrip("/").lower() == "/api/fulltextrepo"
    )


# hasPDF=N 也可能带有 Unpaywall PDF；先收集明确链接，再选择较可靠的入口。
def extract_pdf_url(result: dict[str, Any]) -> str | None:
    # 每个候选同时保留链接和免费访问标记，后者仅用于同类地址中的优先级比较。
    candidates: list[tuple[str, bool]] = []
    for link in full_text_links(result):
        url = as_string(link.get("url"))
        mime_type = (as_string(link.get("mimeType")) or "").split(";")[0].lower()
        style = (as_string(link.get("documentStyle")) or "").lower()
        # DOI/HTML 详情页不能当作 PDF；明确的格式或 MIME 标记也支持无 .pdf 后缀的下载 URL。
        if url and (
            mime_type == "application/pdf"
            or style == "pdf"
            or url.split("?", 1)[0].split("#", 1)[0].lower().endswith(".pdf")
        ):
            candidates.append((url, link.get("availabilityCode") in {"F", "OA"}))

    if candidates:
        # 优先原站/外部地址，再考虑可能过期的代理；同一类地址内优先 Free/OA 链接。
        candidates.sort(key=lambda candidate: (is_epmc_file_proxy(candidate[0]), not candidate[1]))
        url = candidates[0][0]
        # 仅对已识别的 ChemRxiv DOI 替换文件代理；其他平台的代理仍使用上游原值。
        if is_epmc_file_proxy(url) and (native_url := chemrxiv_pdf_url(result)):
            return native_url
        return url

    # ChemRxiv 的索引常只提供 DOI；按完整 DOI 补充原站入口，DOI 自带版本后缀原样保留。
    if native_url := chemrxiv_pdf_url(result):
        return native_url
    pmcid = as_string(result.get("pmcid"))
    has_pdf = result.get("hasPDF") == "Y"
    # 仅在已知 PMC 身份且索引确认存在 PDF 时使用标准入口，无需猜测实际文件名。
    if pmcid and has_pdf:
        return f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/pdf/"
    return None


class EuropePmcAdapter:
    """保持通用索引检索能力，允许子类仅重写查询约束和结果的平台归属。"""

    name = "Europe PMC"
    endpoint = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    pdf_enricher = PreprintPdfEnricher()

    def build_query(self, keyword: str) -> str:
        """默认原样查询；search 通过 self 调用此扩展点，子类可追加平台限制。"""
        return keyword

    # 请求 Europe PMC 搜索接口，并将 JSON 结果规范化为 Paper。
    async def search(
        self,
        *,
        keyword: str,
        page: int,
        page_size: int,
    ) -> tuple[list[Paper], int]:
        params = {
            "query": self.build_query(keyword),
            "format": "json",
            # core 响应包含作者、摘要及全文链接，精简的默认响应不足以完成字段适配。
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
        records = [result for result in results if isinstance(result, dict)]
        papers = [self.to_paper(result) for result in records]
        # 总入口与各平台筛选入口共用原站补查；records 与 papers 保持顺序以核对论文及版本。
        # 补查失败由 enricher 隔离，基础论文仍返回；完成后再按更新的 PDF 访问能力排序。
        await self.pdf_enricher.enrich(records, papers)
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
        if source_code == "PPR":
            # 预印本通常没有期刊名，以发布者展示 bioRxiv 等实际原平台。
            details = result.get("bookOrReportDetails")
            publisher = as_string(details.get("publisher")) if isinstance(details, dict) else None
            source = publisher or source
            # PPR 的总标记有时为 N，但全文链接仍明确标为 Free/OA。
            # 此处仅表示可免费访问，不据此推断论文许可证。
            is_open_access = is_open_access or any(
                link.get("availabilityCode") in {"F", "OA"} and as_string(link.get("url"))
                for link in full_text_links(result)
            )

        paper = Paper(
            id=f"europepmc:{source_code}:{record_id}",
            platform="europepmc",
            # 标题和摘要可能含 XML/HTML 标签及实体，统一清理后作为纯文本展示。
            title=clean_text(result.get("title")) or "Untitled paper",
            year=to_int(result.get("pubYear")),
            authors=extract_authors(result),
            abstract=clean_text(result.get("abstractText")),
            source=source,
            doi=as_string(result.get("doi")),
            url=f"https://europepmc.org/article/{source_code}/{record_id}",
            # 保留真实的 0；缺失值为 None，不借用关联正式出版物的引用量。
            citation_count=to_int(result.get("citedByCount")),
            is_open_access=is_open_access,
            pdf_url=extract_pdf_url(result),
            access_type="detail",
        )
        return paper.model_copy(update={"access_type": access_type(paper)})
