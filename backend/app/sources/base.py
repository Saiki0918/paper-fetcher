from typing import Literal, Protocol

from app.schemas.paper import Paper


class PaperSourceError(Exception):
    """Raised when an academic-paper source cannot return a usable response."""


class PaperSource(Protocol):
    name: str

    # 规定每个论文平台适配器都必须提供统一的异步搜索方法。
    async def search(
        self,
        *,
        keyword: str,
        page: int,
        page_size: int,
    ) -> tuple[list[Paper], int]:
        """Return normalized papers and the total number of matching records."""


# 根据 PDF 和开放获取信息返回排序优先级，数字越小越靠前。
def access_priority(paper: Paper) -> int:
    """Rank records with a known public PDF before less directly accessible records."""
    if paper.is_open_access and paper.pdf_url:
        return 0
    if paper.pdf_url:
        return 1
    if paper.is_open_access:
        return 2
    return 3


# 将论文的 PDF 与开放获取状态转换为前端显示的访问类型。
def access_type(paper: Paper) -> Literal["openPdf", "pdf", "open", "detail"]:
    if paper.is_open_access and paper.pdf_url:
        return "openPdf"
    if paper.pdf_url:
        return "pdf"
    if paper.is_open_access:
        return "open"
    return "detail"
