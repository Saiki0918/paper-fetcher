"""按预印本原平台补充 Europe PMC 未提供的 PDF；不改变检索来源或论文身份。"""

import asyncio
import logging
import re
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.http_client import create_http_client, request_content, request_json
from app.schemas.paper import Paper
from app.sources.base import access_type
from app.utils.parsing import as_string, to_int

logger = logging.getLogger(__name__)


def preprint_platform(record: dict[str, Any]) -> str | None:
    """从 Europe PMC 预印本记录识别原平台，其他文献类型不参与补查。"""
    # bioRxiv 与 medRxiv 共用 DOI 前缀，必须由 PPR 的 publisher 区分原平台。
    if record.get("source") != "PPR":
        return None
    details = record.get("bookOrReportDetails")
    publisher = as_string(details.get("publisher")) if isinstance(details, dict) else None
    return {
        "biorxiv": "biorxiv", "medrxiv": "medrxiv",
        "chemrxiv": "chemrxiv", "research square": "researchsquare",
    }.get((publisher or "").strip().lower())


def chemrxiv_pdf_url(record: dict[str, Any]) -> str | None:
    """使用完整 ChemRxiv DOI 生成原站 PDF 入口，原样保留 DOI 自带的版本后缀。"""
    # 例如 10.26434/chemrxiv.12915779.v3 中的 .v3 就是版本号，已包含在 doi 字符串里。
    # 此处不读取 versionNumber，也不额外追加版本；DOI 未带版本时不会自动补成 v1。
    doi = (as_string(record.get("doi")) or "").strip()
    # PPR 表示预印本；正则核对 ChemRxiv DOI 格式，但不强制要求 .v数字 后缀。
    if record.get("source") == "PPR" and re.fullmatch(
        r"10\.26434/chemrxiv[.-][a-z0-9._-]+", doi, re.IGNORECASE,
    ):
        # 该原站路由接收完整 DOI；它是链接构造规则，不表示本次已下载并验证 PDF。
        return f"https://chemrxiv.org/doi/pdf/{doi}"
    return None


class PdfResolver(Protocol):
    """各平台统一提供 DOI 格式检查和异步补查，返回 None 表示未能确认 PDF 入口。"""

    def accepts(self, record: dict[str, Any]) -> bool:
        """检查该记录的 DOI 格式是否支持当前平台的补查规则。"""
        ...

    async def resolve(self, record: dict[str, Any], client: httpx.AsyncClient) -> str | None:
        """通过共享客户端核对原站元数据，返回已确认归属的链接或 None。"""
        ...


class RxivPdfResolver:
    """两个 Rxiv 站点共用 DOI 明细 API，但 PDF 域名与返回的 server 必须分别核对。"""

    # 两个捕获组分别为基础 DOI 与可选的 vN 版本；10.1101 和 10.64898 均可能属于两个站点。
    doi_pattern = re.compile(r"(10\.(?:1101|64898)/[0-9]+(?:\.[0-9]+)*)(?:v([1-9][0-9]*))?", re.I)

    def __init__(self, server: str) -> None:
        """server 同时选择官方明细 API 路径和最终 PDF 所属的站点。"""
        self.server = server

    def accepts(self, record: dict[str, Any]) -> bool:
        """仅检查 DOI 结构，平台归属与版本有效性在 resolve 中进一步核对。"""
        return self.doi_pattern.fullmatch((as_string(record.get("doi")) or "").strip()) is not None

    async def resolve(self, record: dict[str, Any], client: httpx.AsyncClient) -> str | None:
        """用官方明细确认唯一的论文版本，再生成对应站点的 PDF 阅读地址。"""
        match = self.doi_pattern.fullmatch((as_string(record.get("doi")) or "").strip())
        if not match:
            return None
        doi, suffix_version = match.groups()
        # 先读取索引明确给出的版本；若 DOI 也带版本，两者必须一致。
        version = to_int(record.get("versionNumber"))
        if suffix_version:
            if version is not None and version != int(suffix_version):
                return None
            version = int(suffix_version)
        # bioRxiv 和 medRxiv 共用 api.biorxiv.org，由路径中的 server 选择站点。
        # 此 API 返回 DOI、server、version 等明细，没有直接 PDF 字段。
        payload = await request_json(f"https://api.biorxiv.org/details/{self.server}/{doi}", client=client)
        collection = payload.get("collection") if isinstance(payload, dict) else None
        if not isinstance(collection, list):
            return None
        # 只使用同篇 DOI、同一原平台且具有有效版本号的记录，避免误用正式出版物或另一站点。
        matches = [item for item in collection if isinstance(item, dict)
                   and (as_string(item.get("doi")) or "").lower() == doi.lower()
                   and (as_string(item.get("server")) or "").lower() == self.server
                   and (to_int(item.get("version")) or 0) > 0]
        if version is not None:
            # 版本已知时必须在官方明细中找到对应版本，不能默认替换成最新版。
            matches = [item for item in matches if to_int(item.get("version")) == version]
        elif len({to_int(item.get("version")) for item in matches}) > 1:
            # 索引未给版本时按收录的发布日期匹配；无法确定时不擅自选择最新版。
            date = as_string(record.get("firstPublicationDate"))
            matches = [item for item in matches if date and item.get("date") == date]
        versions = {to_int(item.get("version")) for item in matches}
        # 没有匹配或仍有多个候选版本时放弃补充；只有一个官方版本时也不需要假定 v1。
        if len(versions) != 1:
            return None
        selected = matches[0]
        # 官方将该版本标为撤回时，不新增指向该版本的 PDF 入口。
        if "withdraw" in (as_string(selected.get("type")) or "").lower():
            return None
        # 使用已核实的版本拼接原站路由；这里生成阅读入口，不逐篇请求 PDF 文件。
        return f"https://www.{self.server}.org/content/{doi}v{to_int(selected.get('version'))}.full.pdf"


class ArticleLinks(HTMLParser):
    """收集原文页声明的 DOI 和候选链接，由平台解析器进一步核对论文与版本。"""

    def __init__(self) -> None:
        # 把 HTML 属性中的 &amp; 还原成 &，使下载链接的查询参数保持正确。
        super().__init__(convert_charrefs=True)
        self.dois: list[str] = []
        self.pdfs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """兼容引用元标签和下载按钮，先收集候选，交由调用方核对同篇与同版本。"""
        attributes = dict(attrs)
        if tag == "meta":
            name, content = attributes.get("name"), attributes.get("content")
            if name == "citation_doi" and content:
                self.dois.append(content.strip())
            elif name == "citation_pdf_url" and content:
                self.pdfs.append(content)
        elif tag == "a" and attributes.get("href"):
            # 页面下载按钮通常是 <a href="...">；这里先收集，后续再过滤无关链接。
            self.pdfs.append(attributes["href"])


class ResearchSquarePdfResolver:
    """定位 DOI 对应的版本页，仅使用页面实际提供且与该版本一致的 PDF 链接。"""

    # 例如 10.21203/rs.3.rs-11017119/v1，分别提取文章 ID rs-11017119 和版本 1。
    doi_pattern = re.compile(r"10\.21203/rs\.3\.(rs-[0-9]+)/v([1-9][0-9]*)", re.I)

    def accepts(self, record: dict[str, Any]) -> bool:
        """Research Square 的版本号属于 DOI 路径，必须能明确提取后才尝试补查。"""
        return self.doi_pattern.fullmatch((as_string(record.get("doi")) or "").strip()) is not None

    async def resolve(self, record: dict[str, Any], client: httpx.AsyncClient) -> str | None:
        """读取对应版本的原文页，核对页面 DOI 和下载链接的域名、文章及版本。"""
        doi = (as_string(record.get("doi")) or "").strip()
        match = self.doi_pattern.fullmatch(doi)
        if not match:
            return None
        article, version = match.groups()
        # DOI 的 /vN 是版本来源；索引也提供版本时，核对两者是否冲突。
        if record.get("versionNumber") is not None and to_int(record.get("versionNumber")) != int(version):
            return None
        # 拼接的是对应版本的原文 HTML 页面地址，最终 PDF 链接还需从页面读取。
        page = f"https://www.researchsquare.com/article/{article.lower()}/v{version}"
        content = await request_content(page, headers={"Accept": "text/html"}, client=client)
        parser = ArticleLinks()
        parser.feed(content.decode("utf-8", errors="replace"))
        # 页面必须声明同篇 DOI；验证页、错误页或跳转到其他文章时不返回 PDF。
        if doi.lower() not in {value.lower() for value in parser.dois}:
            return None
        # expected_path 只用于核对候选链接，不能直接作为解析成功的下载地址返回。
        expected_path = f"/article/{article.lower()}/v{version}.pdf"
        for link in parser.pdfs:
            # 将相对 href 补为绝对 URL，保留原页面提供的 ?c=... 等查询参数。
            url = urljoin(page, link)
            try:
                parsed = urlsplit(url)
            except ValueError:
                continue
            # latest.pdf 可能跳转到不同版本；只接受页面实际给出的同篇、同版本链接。
            if (parsed.scheme == "https" and parsed.netloc == "www.researchsquare.com"
                    and parsed.path == expected_path):
                return url
        return None


class PreprintPdfEnricher:
    """按平台分发缺失 PDF 的补查，并在限流、失败或超时后保留基础搜索结果。"""

    # 单条补查失败不影响基本检索；整页补查也受预算约束，避免大页请求串行等待。
    budget_seconds = 8.0
    request_timeout_seconds = 5.0
    concurrency = 4
    # ChemRxiv 在同步字段解析时按 DOI 生成入口；这里注册的是需要额外网络请求的平台。
    resolvers: dict[str, PdfResolver] = {
        "biorxiv": RxivPdfResolver("biorxiv"),
        "medrxiv": RxivPdfResolver("medrxiv"),
        "researchsquare": ResearchSquarePdfResolver(),
    }

    async def enrich(self, records: list[dict[str, Any]], papers: list[Paper]) -> None:
        """接收顺序一一对应的原始记录与论文模型，仅将成功补齐的 PDF 写回模型列表。"""
        # 仅补查缺少 PDF 且原平台、DOI 格式均已识别的记录，保留已有明确 PDF。
        # 此时两份列表尚未排序，index 用于把补查结果写回同一篇论文。
        pending = [(record, index, platform) for index, (record, paper) in enumerate(zip(records, papers))
                   if not paper.pdf_url and (platform := preprint_platform(record)) in self.resolvers
                   and self.resolvers[platform].accepts(record)]
        if not pending:
            return
        semaphore = asyncio.Semaphore(self.concurrency)
        rate_limited: set[str] = set()

        async def supplement(record: dict[str, Any], index: int, platform: str, client: httpx.AsyncClient) -> None:
            """在共享并发额度内补充单篇论文，失败范围限制在当前记录或被限流的服务。"""
            # 两个 Rxiv 的 API 共用域名，其限流状态也需共用。
            service = "rxiv" if platform in {"biorxiv", "medrxiv"} else platform
            async with semaphore:
                if service in rate_limited:
                    return
                try:
                    pdf_url = await self.resolvers[platform].resolve(record, client)
                    if pdf_url:
                        paper = papers[index].model_copy(update={"pdf_url": pdf_url})
                        # PDF 补齐后同步更新前端访问类型，不改写原来的开放获取标记。
                        papers[index] = paper.model_copy(update={"access_type": access_type(paper)})
                except (httpx.HTTPError, ValueError) as exc:
                    # 429 后停止该服务排队中的补查；其他网络或解析错误仅影响当前论文。
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                        rate_limited.add(service)
                    logger.warning("%s PDF 补查失败（%s），保留详情页: %s", platform, record.get("id"), str(exc) or type(exc).__name__)

        # 共用客户端复用连接；HTTP 超时限制单次请求，wait_for 限制整页补查总耗时。
        async with create_http_client(timeout=self.request_timeout_seconds) as client:
            tasks = [supplement(record, index, platform, client) for record, index, platform in pending]
            try:
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=self.budget_seconds)
            except asyncio.TimeoutError:
                # 未完成任务被取消，已写回 papers 的 PDF 保留，未补齐的论文继续提供详情页。
                logger.warning("预印本 PDF 补查达到 %.1f 秒预算，返回已取得的结果", self.budget_seconds)
