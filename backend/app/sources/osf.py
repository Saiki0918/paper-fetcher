"""OSF 社区预印本的标题关键词搜索，可按发布社区筛选。"""

import asyncio
import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.http_client import create_http_client, request_json
from app.schemas.paper import Paper
from app.sources.base import PaperSourceError, access_priority, access_type
from app.utils.parsing import as_string, to_int
from app.utils.text import clean_text

logger = logging.getLogger(__name__)


def embedded_data(record: dict[str, Any], field: str) -> Any:
    """读取 OSF 的 embeds[field].data；关联资源不在标准 JSON:API 的 included 中。"""
    embeds = record.get("embeds")
    resource = embeds.get(field) if isinstance(embeds, dict) else None
    return resource.get("data") if isinstance(resource, dict) else None


def api_url(value: Any) -> str | None:
    """兼容字符串与 {href, meta} 链接对象，仅跟随 OSF v2 官方 HTTPS 接口。"""
    url = as_string(value.get("href")) if isinstance(value, dict) else as_string(value)
    if not url:
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    # related 和 next 都来自外部响应，统一限制域名和路径后才发起补查。
    return url if parsed.scheme == "https" and parsed.netloc == "api.osf.io" and parsed.path.startswith("/v2/") else None


def related_url(record: dict[str, Any], field: str) -> str | None:
    """从关系描述中取关联资源的查询地址，而非将关系 ID 自行拼成下载链接。"""
    relationships = record.get("relationships")
    resource = relationships.get(field) if isinstance(relationships, dict) else None
    links = resource.get("links") if isinstance(resource, dict) else None
    return api_url(links.get("related")) if isinstance(links, dict) else None


class OsfPreprintAdapter:
    """检索 OSF 合集或指定社区，通过独立关联接口补齐主文件与署名作者。"""

    endpoint = "https://api.osf.io/v2/preprints/"
    # 补充元数据共享时间预算，避免大页结果或单个异常接口拖住整个搜索。
    metadata_budget_seconds = 8.0
    metadata_request_timeout_seconds = 4.0
    metadata_concurrency = 4

    def __init__(self, provider: str | None = None, name: str = "OSF Preprints") -> None:
        """未指定 provider 时搜索合集；指定后将社区标识用于路由和结果归属。"""
        self.provider = provider
        self.platform = provider or "osf"
        self.name = name
        # 专属社区入口避免在整个 OSF 合集中筛选，合集本身仍使用 /preprints/。
        if provider:
            self.endpoint = f"https://api.osf.io/v2/providers/preprints/{provider}/preprints/"

    async def search(
        self, *, keyword: str, page: int, page_size: int,
    ) -> tuple[list[Paper], int]:
        """按标题关键词分页检索；基础检索失败报错，关联元数据失败允许降级返回。"""
        params: dict[str, Any] = {
            "filter[title]": keyword,
            "page": page,
            # 方括号交给 HTTP 客户端编码一次；预先写成 %5B/%5D 会造成重复转义。
            "page[size]": page_size,
        }
        try:
            # 社区已由 endpoint 限定；先取基础结果，不对整个列表执行嵌套 embed。
            payload = await request_json(self.endpoint, params=params)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.warning("%s 基础检索返回 HTTP %s", self.name, status)
            reason = "上游网关或服务暂时不可用" if status >= 500 else "上游拒绝请求"
            if status == 429:
                reason = "上游请求限流，请稍后重试"
            raise PaperSourceError(f"{self.name} 返回 HTTP {status}：{reason}") from exc
        except httpx.TimeoutException as exc:
            raise PaperSourceError(f"{self.name} 基础检索超时，请稍后重试") from exc
        except (httpx.HTTPError, ValueError) as exc:
            logger.exception("%s 预印本搜索失败", self.name)
            raise PaperSourceError(
                f"{self.name} 预印本搜索失败: {str(exc) or type(exc).__name__}"
            ) from exc

        # data=[] 是有效的空搜索结果，缺少 data 列表则视为上游响应契约异常。
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise PaperSourceError(f"{self.name} 返回的数据中没有论文列表")
        links = payload.get("links") or {}
        # OSF 将总数放在 links.meta 中；不能用当前页 data 的长度代替搜索总数。
        meta = links.get("meta") if isinstance(links, dict) else None
        total = to_int(meta.get("total")) if isinstance(meta, dict) else 0
        records = [record for record in payload["data"] if isinstance(record, dict)]
        # 补查会把成功字段写回 embeds，统一转换后即可根据新增的 PDF 能力排序。
        await self.enrich_records(records)
        papers = [self.to_paper(record) for record in records]
        return sorted(papers, key=access_priority), total or 0

    async def enrich_records(self, records: list[dict[str, Any]]) -> None:
        """分别获取主文件和署名作者；任一补充接口失败时保留其他已取得的字段。"""
        # 所有记录共享并发额度；一旦收到限流响应，尚未发出的补查立即停止。
        semaphore = asyncio.Semaphore(self.metadata_concurrency)
        rate_limited = asyncio.Event()

        async def enrich(record: dict[str, Any], field: str, client: httpx.AsyncClient) -> None:
            """独立回填一个关系字段；作者列表需要继续跟随分页并保留已取得的姓名。"""
            url = related_url(record, field)
            if not url or embedded_data(record, field) is not None:
                return
            params = {"page[size]": 100} if field == "bibliographic_contributors" else None
            contributors: list[dict[str, Any]] = []
            # 防止异常 next 链接形成循环，反复消耗补查时间预算。
            visited: set[str] = set()
            while url and url not in visited:
                visited.add(url)
                try:
                    async with semaphore:
                        if rate_limited.is_set():
                            return
                        payload = await request_json(url, params=params, client=client)
                    data = payload.get("data") if isinstance(payload, dict) else None
                    if not isinstance(data, list if field == "bibliographic_contributors" else dict):
                        return
                    if field == "bibliographic_contributors":
                        contributors.extend(item for item in data if isinstance(item, dict))
                        # 保存当前页进度的独立快照，后续分页继续累积时不共享可变列表。
                        data = contributors.copy()
                    embeds = record.get("embeds")
                    if not isinstance(embeds, dict):
                        embeds = record["embeds"] = {}
                    # 每次成功即回写；后续分页失败或整体超时都不会丢失已完成的字段。
                    embeds[field] = {"data": data}
                    # 作者接口默认已展开 users；仅跟随作者分页，不请求每位作者个人接口。
                    links = payload.get("links")
                    url = api_url(links.get("next")) if field == "bibliographic_contributors" and isinstance(links, dict) else None
                    # next 已包含后续页参数，不再覆盖为首页的 page[size] 请求参数。
                    params = None
                except (httpx.HTTPError, ValueError) as exc:
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                        rate_limited.set()
                    logger.warning("%s %s 元数据暂不可用: %s", self.name, field, str(exc) or type(exc).__name__)
                    return

        # 私有或已撤回记录不进行公开文件和作者补查，基础记录仍由转换流程处理。
        eligible = []
        for record in records:
            attributes = record.get("attributes") or {}
            if isinstance(attributes, dict) and attributes.get("public") is True and not attributes.get("date_withdrawn"):
                eligible.append(record)
        pending = [(record, field) for record in eligible
                   for field in ("primary_file", "bibliographic_contributors")
                   if embedded_data(record, field) is None and related_url(record, field)]
        if not pending:
            return
        # 关联请求共用连接池，并发限制、单次超时和整批预算分别控制资源与等待时间。
        async with create_http_client(timeout=self.metadata_request_timeout_seconds) as client:
            tasks = [enrich(record, field, client) for record, field in pending]
            try:
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=self.metadata_budget_seconds)
            except asyncio.TimeoutError:
                # wait_for 取消未完成的请求；已写入记录的 PDF 和作者仍会返回。
                logger.warning("%s 元数据补充达到 %.1f 秒预算，返回已取得的结果", self.name, self.metadata_budget_seconds)

    def to_paper(self, record: dict[str, Any]) -> Paper:
        """组合基础属性和补查到的 embeds，保持预印本 DOI、版本及访问状态的含义。"""
        attributes = record.get("attributes")
        attributes = attributes if isinstance(attributes, dict) else {}
        links = record.get("links")
        links = links if isinstance(links, dict) else {}
        contributors = embedded_data(record, "bibliographic_contributors")
        authors: list[str] = []
        for contributor in contributors if isinstance(contributors, list) else []:
            if not isinstance(contributor, dict):
                continue
            user = embedded_data(contributor, "users")
            user_attrs = user.get("attributes", {}) if isinstance(user, dict) else {}
            contributor_attrs = contributor.get("attributes") or {}
            if not isinstance(contributor_attrs, dict):
                continue
            name = as_string(user_attrs.get("full_name")) if isinstance(user_attrs, dict) else None
            # 未注册 OSF 账号的署名作者没有 users 资源，姓名保存在 contributor 属性中。
            name = name or as_string(contributor_attrs.get("unregistered_contributor"))
            if name:
                authors.append(name)

        withdrawn = bool(attributes.get("date_withdrawn"))
        is_public = attributes.get("public") is True and not withdrawn
        file = embedded_data(record, "primary_file")
        file_attrs = file.get("attributes", {}) if isinstance(file, dict) else {}
        file_links = file.get("links", {}) if isinstance(file, dict) else {}
        pdf_url = None
        # OSF 主文件也可能是 DOCX；确认扩展名后才提供 PDF 按钮。
        if is_public and isinstance(file_attrs, dict) and isinstance(file_links, dict):
            filename = as_string(file_attrs.get("name")) or ""
            if filename.lower().endswith(".pdf"):
                pdf_url = as_string(file_links.get("download"))

        relationships = record.get("relationships") or {}
        provider = relationships.get("provider", {}) if isinstance(relationships, dict) else {}
        provider_data = provider.get("data", {}) if isinstance(provider, dict) else {}
        provider_id = as_string(provider_data.get("id")) if isinstance(provider_data, dict) else None
        # OSF 的 ID 可能自带 _vN 版本后缀，结果 ID 和详情页均保留完整原值。
        record_id = as_string(record.get("id")) or "unknown"
        date = as_string(attributes.get("date_published")) or ""
        # attributes.doi 是关联正式出版物的 DOI，预印本自身 DOI 位于 links.preprint_doi。
        preprint_doi = as_string(links.get("preprint_doi"))
        doi = preprint_doi.removeprefix("https://doi.org/") if preprint_doi else None
        # 当前接口不提供引用量，保留 None，避免将缺失统计展示为零引用。
        paper = Paper(
            id=f"{self.platform}:{record_id}",
            platform=self.platform,
            title=clean_text(attributes.get("title")) or "Untitled paper",
            year=to_int(date[:4]),
            authors=authors,
            abstract=clean_text(attributes.get("description")),
            source=f"OSF · {provider_id}" if provider_id else self.name,
            doi=doi,
            url=as_string(links.get("html")) or f"https://osf.io/{record_id}/",
            is_open_access=is_public,
            pdf_url=pdf_url,
        )
        return paper.model_copy(update={"access_type": access_type(paper)})
