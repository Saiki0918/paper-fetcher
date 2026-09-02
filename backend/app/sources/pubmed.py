import logging
import re
from typing import Final
from xml.etree import ElementTree

import httpx

from app.core.config import settings
from app.core.http_client import create_http_client, request_content, request_json
from app.schemas.paper import Paper
from app.sources.base import PaperSourceError, access_priority, access_type
from app.utils.xml import xml_text


class PubMedError(PaperSourceError):
    """Raised when PubMed cannot return a usable search response."""


logger = logging.getLogger(__name__)


EUTILS_BASE: Final = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


# 从 PubMed 记录的多个日期位置依次读取发表年份。
def xml_year(article: ElementTree.Element) -> int | None:
    for path in (
        "./MedlineCitation/Article/Journal/JournalIssue/PubDate/Year",
        "./MedlineCitation/Article/ArticleDate/Year",
    ):
        value = xml_text(article.find(path))
        if value and value.isdigit():
            return int(value)

    medline_date = xml_text(
        article.find("./MedlineCitation/Article/Journal/JournalIssue/PubDate/MedlineDate")
    )
    match = re.search(r"\b(1[89]\d{2}|20\d{2})\b", medline_date or "")
    return int(match.group(1)) if match else None


# 将 PubMed XML 作者节点转换为可展示的姓名列表。
def xml_authors(article: ElementTree.Element) -> list[str]:
    authors: list[str] = []
    for author in article.findall("./MedlineCitation/Article/AuthorList/Author"):
        collective_name = xml_text(author.find("CollectiveName"))
        if collective_name:
            authors.append(collective_name)
            continue
        name = " ".join(
            value
            for value in (
                xml_text(author.find("ForeName")),
                xml_text(author.find("LastName")),
            )
            if value
        )
        if name:
            authors.append(name)
    return authors


# 合并 PubMed 摘要的多个分段，并保留分段标签。
def xml_abstract(article: ElementTree.Element) -> str | None:
    sections: list[str] = []
    for abstract_text in article.findall("./MedlineCitation/Article/Abstract/AbstractText"):
        text = xml_text(abstract_text)
        if not text:
            continue
        label = abstract_text.get("Label")
        sections.append(f"{label}: {text}" if label else text)
    return " ".join(sections) or None


# 收集 PubMed 记录中的 DOI、PMC ID 等文章标识符。
def article_ids(article: ElementTree.Element) -> dict[str, str]:
    return {
        id_type: identifier
        for identifier_element in article.findall("./PubmedData/ArticleIdList/ArticleId")
        if (id_type := identifier_element.get("IdType"))
        and (identifier := xml_text(identifier_element))
    }


class PubMedAdapter:
    name = "PubMed"
    search_endpoint = f"{EUTILS_BASE}/esearch.fcgi"
    fetch_endpoint = f"{EUTILS_BASE}/efetch.fcgi"

    # 创建 NCBI 请求的公共参数，并在配置存在时附带邮箱和 API Key。
    def request_params(self) -> dict[str, str]:
        params = {"tool": "paper_search"}
        if settings.ncbi_email:
            params["email"] = settings.ncbi_email
        if settings.ncbi_api_key:
            params["api_key"] = settings.ncbi_api_key
        return params

    # 先用 esearch 获得 PMID，再用 efetch 获取并规范化论文详情。
    async def search(
        self,
        *,
        keyword: str,
        page: int,
        page_size: int,
    ) -> tuple[list[Paper], int]:
        search_params: dict[str, str | int] = {
            "db": "pubmed",
            "term": keyword,
            "retstart": (page - 1) * page_size,
            "retmax": page_size,
            "retmode": "json",
            **self.request_params(),
        }
        try:
            async with create_http_client(
                timeout=settings.http_timeout_seconds,
            ) as client:
                search_payload = await request_json(
                    self.search_endpoint,
                    params=search_params,
                    client=client,
                )
                ids = self.extract_ids(search_payload)
                total = self.extract_total(search_payload)
                if not ids:
                    return [], total

                fetch_content = await request_content(
                    self.fetch_endpoint,
                    params={
                        "db": "pubmed",
                        "id": ",".join(ids),
                        "retmode": "xml",
                        **self.request_params(),
                    },
                    client=client,
                )
            root = ElementTree.fromstring(fetch_content)
        except (httpx.HTTPError, ValueError, ElementTree.ParseError) as exc:
            logger.exception("PubMed 请求或 XML 解析失败")
            raise PubMedError(f"PubMed 请求或 XML 解析失败: {exc}") from exc

        papers_by_id = {
            paper.id.removeprefix("pubmed:"): paper
            for article in root.findall("./PubmedArticle")
            if (paper := self.to_paper(article))
        }
        papers = [papers_by_id[pmid] for pmid in ids if pmid in papers_by_id]
        return sorted(papers, key=access_priority), total

    @staticmethod
    # 从 esearch JSON 中读取本页需要查询详情的 PMID 列表。
    def extract_ids(payload: object) -> list[str]:
        if not isinstance(payload, dict):
            raise PubMedError
        result = payload.get("esearchresult")
        ids = result.get("idlist") if isinstance(result, dict) else None
        if not isinstance(ids, list) or not all(isinstance(identifier, str) for identifier in ids):
            raise PubMedError
        return ids

    @staticmethod
    # 从 esearch JSON 中读取该关键词在 PubMed 的总命中数量。
    def extract_total(payload: object) -> int:
        if not isinstance(payload, dict):
            raise PubMedError
        result = payload.get("esearchresult")
        count = result.get("count") if isinstance(result, dict) else None
        return int(count) if isinstance(count, str) and count.isdigit() else 0

    @staticmethod
    # 从一条 PubMed XML 论文记录中提取统一论文字段。
    def to_paper(article: ElementTree.Element) -> Paper | None:
        pmid = xml_text(article.find("./MedlineCitation/PMID"))
        if not pmid:
            return None

        ids = article_ids(article)
        pmcid = ids.get("pmc")
        detail_url = (
            f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
            if pmcid
            else f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        )

        paper = Paper(
            id=f"pubmed:{pmid}",
            platform="pubmed",
            title=xml_text(article.find("./MedlineCitation/Article/ArticleTitle")) or "Untitled paper",
            year=xml_year(article),
            authors=xml_authors(article),
            abstract=xml_abstract(article),
            source=xml_text(article.find("./MedlineCitation/Article/Journal/Title")) or "PubMed",
            doi=ids.get("doi"),
            url=detail_url,
            citation_count=None,
            is_open_access=bool(pmcid),
            pdf_url=f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/pdf/" if pmcid else None,
            access_type="detail",
        )
        return paper.model_copy(update={"access_type": access_type(paper)})
