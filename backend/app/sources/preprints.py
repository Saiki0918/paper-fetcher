"""通过 Europe PMC 的关键词索引检索指定预印本平台；覆盖范围以索引收录为准。"""

from typing import Any

from app.schemas.paper import Paper
from app.sources.base import access_type
from app.sources.europepmc import EuropePmcAdapter
from app.utils.parsing import as_string


class IndexedPreprintAdapter(EuropePmcAdapter):
    """区分用户选择的发布平台，共用 Europe PMC 的搜索、字段解析及原站 PDF 补查。"""

    def __init__(self, platform: str, publisher: str) -> None:
        """platform 用于项目路由和结果标识，publisher 对应 Europe PMC 的发布者字段。"""
        self.platform = platform
        self.name = publisher

    def build_query(self, keyword: str) -> str:
        # 同时限定预印本类型和发布平台，避免混入同主题的正式期刊论文。
        # 父类 search() 调用 self.build_query()，因此会采用此处的平台筛选条件。
        return f'({keyword}) AND SRC:PPR AND PUBLISHER:"{self.name}"'

    def to_paper(self, result: dict[str, Any]) -> Paper:
        """共用索引字段解析，再将平台标识和详情入口改为用户所选的发布平台。"""
        paper = EuropePmcAdapter.to_paper(result)
        # DOI 跳转到原平台；原站 PDF 补查由继承的搜索流程按 publisher 分别处理。
        # 此处设置的 url 是论文详情入口，与之后补充的 pdf_url 是两个独立字段。
        doi = as_string(result.get("doi"))
        # 平台前缀区分同篇论文在不同搜索入口的记录；跨平台合并时仍按 DOI 等信息去重。
        paper = paper.model_copy(update={
            "id": f"{self.platform}:{result.get('id') or doi or paper.id}",
            "platform": self.platform,
            "source": self.name,
            "url": f"https://doi.org/{doi}" if doi else paper.url,
        })
        return paper.model_copy(update={"access_type": access_type(paper)})
