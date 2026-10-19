"""仅检索 Zenodo 中标记为预印本的公开记录。"""

import logging
from typing import Any

import httpx

from app.core.http_client import request_json
from app.schemas.paper import Paper
from app.sources.base import PaperSourceError, access_priority, access_type
from app.utils.parsing import as_list, as_string, to_int
from app.utils.text import clean_text

logger = logging.getLogger(__name__)


class ZenodoAdapter:
    """复用 Zenodo 记录搜索，只把预印本文献作为论文结果返回。"""

    name = "Zenodo Preprints"
    endpoint = "https://zenodo.org/api/records"

    async def search(
        self, *, keyword: str, page: int, page_size: int,
    ) -> tuple[list[Paper], int]:
        """使用官方文献子类型筛选与分页，不将数据集、软件等成果混入搜索结果。"""
        params = {
            "q": keyword,
            # preprint 是 publication 的子类型，两个条件需要同时传递。
            "type": "publication",
            "subtype": "preprint",
            "page": page,
            "size": page_size,
            "sort": "bestmatch",
        }
        try:
            payload = await request_json(self.endpoint, params=params)
        except (httpx.HTTPError, ValueError) as exc:
            logger.exception("Zenodo 预印本搜索失败")
            raise PaperSourceError(f"Zenodo 预印本搜索失败: {str(exc) or type(exc).__name__}") from exc

        hits = payload.get("hits") if isinstance(payload, dict) else None
        # 必须区分正常的空 hits 与上游错误对象，避免把接口故障展示为零命中。
        if not isinstance(hits, dict) or not isinstance(hits.get("hits"), list):
            raise PaperSourceError("Zenodo 返回的数据中没有论文列表")
        total = hits.get("total")
        # 兼容 Elasticsearch 的整数总数和 {value, relation} 总数格式。
        if isinstance(total, dict):
            total = total.get("value")
        papers = [self.to_paper(item) for item in hits["hits"] if isinstance(item, dict)]
        return sorted(papers, key=access_priority), to_int(total) or 0

    @staticmethod
    def to_paper(item: dict[str, Any]) -> Paper:
        """从记录元数据提取论文字段，只为开放记录选择明确的 PDF 文件。"""
        # 可选元数据和链接可能为 null，统一为空对象后再读取具体字段。
        metadata = item.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        links = item.get("links")
        links = links if isinstance(links, dict) else {}
        authors = [
            name for creator in as_list(metadata.get("creators"))
            if isinstance(creator, dict) and (name := as_string(creator.get("name")))
        ]
        is_open = metadata.get("access_right") == "open"
        pdf_url = None
        # 受限或禁运文件不能因返回了文件元数据而显示为可下载 PDF。
        if is_open:
            for file in as_list(item.get("files")):
                if not isinstance(file, dict):
                    continue
                filename = as_string(file.get("key")) or ""
                # 一条记录可附带 ZIP 等多个文件；首个带下载地址的 PDF 才用于阅读按钮。
                if not filename.lower().endswith(".pdf"):
                    continue
                file_links = file.get("links") or {}
                if isinstance(file_links, dict):
                    # 保留官方 URL 已编码的文件名，避免特殊字符被重复编码而导致下载失败。
                    pdf_url = as_string(file_links.get("self")) or as_string(file_links.get("content"))
                if pdf_url:
                    break
        date = as_string(metadata.get("publication_date")) or ""
        record_id = str(item.get("id") or "unknown")
        # Zenodo 的浏览量、下载量不等于引用量，此处保留引用统计的 None 默认值。
        paper = Paper(
            id=f"zenodo:{record_id}",
            platform="zenodo",
            title=clean_text(metadata.get("title")) or "Untitled paper",
            year=to_int(date[:4]),
            authors=authors,
            abstract=clean_text(metadata.get("description")),
            source="Zenodo · Preprint",
            doi=as_string(metadata.get("doi")) or as_string(item.get("doi")),
            url=as_string(links.get("self_html")) or f"https://zenodo.org/records/{record_id}",
            is_open_access=is_open,
            pdf_url=pdf_url,
        )
        # 开放记录也可能只有 ZIP，访问类型需同时依据开放标记和实际 PDF 链接计算。
        return paper.model_copy(update={"access_type": access_type(paper)})
