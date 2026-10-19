"""HAL 的预印本 / 工作论文关键词检索。"""

import logging
from typing import Any

import httpx

from app.core.http_client import request_json
from app.schemas.paper import Paper
from app.sources.base import PaperSourceError, access_priority, access_type
from app.utils.parsing import as_list, as_string, first_string, to_int
from app.utils.text import clean_text

logger = logging.getLogger(__name__)


class HalAdapter:
    """将 HAL 搜索结果映射为统一论文结构，仅覆盖预印本 / 工作论文类别。"""

    name = "HAL Preprints"
    endpoint = "https://api.archives-ouvertes.fr/search/"

    async def search(
        self, *, keyword: str, page: int, page_size: int,
    ) -> tuple[list[Paper], int]:
        """按相关度获取一页记录，再按本项目的访问能力规则排列当前页。"""
        params = {
            "q": keyword,
            # HAL 还收录期刊、会议等成果；UNDEFINED 为预发表稿 / 工作论文类别。
            "fq": "docType_s:UNDEFINED",
            "wt": "json",
            # HAL 使用从 0 开始的记录偏移量，项目接口使用从 1 开始的页码。
            "start": (page - 1) * page_size,
            "rows": page_size,
            "sort": "score desc",
            # 只请求卡片展示所需字段，减少多语言全文等无关数据的传输。
            "fl": "halId_s,title_s,authFullName_s,abstract_s,doiId_s,uri_s,"
                  "fileMain_s,producedDateY_i,openAccess_bool",
        }
        try:
            payload = await request_json(self.endpoint, params=params)
        except (httpx.HTTPError, ValueError) as exc:
            logger.exception("HAL 预印本搜索失败")
            raise PaperSourceError(f"HAL 预印本搜索失败: {str(exc) or type(exc).__name__}") from exc

        response = payload.get("response") if isinstance(payload, dict) else None
        # 空 docs 是正常的零命中；缺失列表表示响应异常，交由路由报告来源失败。
        if not isinstance(response, dict) or not isinstance(response.get("docs"), list):
            raise PaperSourceError("HAL 返回的数据中没有论文列表")
        papers = [self.to_paper(doc) for doc in response["docs"] if isinstance(doc, dict)]
        return sorted(papers, key=access_priority), to_int(response.get("numFound")) or 0

    @staticmethod
    def to_paper(doc: dict[str, Any]) -> Paper:
        """展开 HAL 的数组字段并清理摘要中的标记，保留官方详情页和主文件地址。"""
        record_id = as_string(doc.get("halId_s")) or "unknown"
        # 标题、摘要及 DOI 可能以数组返回；展示首个有效文本，不将多语种内容拼成一段。
        # HAL 未提供引用统计，保留 Paper.citation_count 的 None 默认值。
        paper = Paper(
            id=f"hal:{record_id}",
            platform="hal",
            title=clean_text(first_string(doc.get("title_s"))) or "Untitled paper",
            year=to_int(doc.get("producedDateY_i")),
            authors=[name for value in as_list(doc.get("authFullName_s"))
                     if (name := as_string(value))],
            abstract=clean_text(first_string(doc.get("abstract_s"))),
            source="HAL · Preprint / Working paper",
            doi=first_string(doc.get("doiId_s")),
            url=as_string(doc.get("uri_s")) or f"https://hal.science/{record_id}",
            is_open_access=doc.get("openAccess_bool") is True,
            # 主文件地址可能以 /document 结尾，直接使用 API 原值；缺失时只保留详情入口。
            pdf_url=as_string(doc.get("fileMain_s")),
        )
        # 开放标记和文件链接分别解析完成后，再统一计算前端使用的访问类型。
        return paper.model_copy(update={"access_type": access_type(paper)})
