import asyncio

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.schemas.paper import ApiError, Paper, PaperSearchMeta, PaperSearchResponse
from app.sources.arxiv import ArxivAdapter
from app.sources.base import PaperSource, PaperSourceError, access_priority
from app.sources.crossref import CrossrefAdapter
from app.sources.dblp import DblpAdapter
from app.sources.doaj import DoajAdapter
from app.sources.europepmc import EuropePmcAdapter
from app.sources.openalex import OpenAlexAdapter
from app.sources.pubmed import PubMedAdapter

router = APIRouter(prefix="/api/papers", tags=["papers"])

sources: dict[str, PaperSource] = {
    "openalex": OpenAlexAdapter(),
    "crossref": CrossrefAdapter(),
    "arxiv": ArxivAdapter(),
    "europepmc": EuropePmcAdapter(),
    "pubmed": PubMedAdapter(),
    "dblp": DblpAdapter(),
    "doaj": DoajAdapter(),
}
available_platforms = ["all", *sources]


# 创建统一的搜索元数据对象，供成功和失败响应复用。
def make_meta(
    *,
    query: str,
    page: int,
    page_size: int,
    total: int,
    requested_platform: str,
    searched_platforms: list[str],
    total_is_approximate: bool = False,
    failed_platforms: list[str] | None = None,
) -> PaperSearchMeta:
    return PaperSearchMeta(
        query=query,
        page=page,
        page_size=page_size,
        total=total,
        requested_platform=requested_platform,
        searched_platforms=searched_platforms,
        total_is_approximate=total_is_approximate,
        failed_platforms=failed_platforms or [],
    )


# 将错误信息包装成符合前端约定的 JSON 响应。
def error_response(
    *,
    query: str,
    page: int,
    page_size: int,
    requested_platform: str,
    code: str,
    message: str,
    status_code: int,
) -> JSONResponse:
    payload = PaperSearchResponse(
        data=[],
        meta=make_meta(
            query=query,
            page=page,
            page_size=page_size,
            total=0,
            requested_platform=requested_platform,
            searched_platforms=[],
        ),
        error=ApiError(code=code, message=message),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(by_alias=True))


# 为论文生成跨平台去重所需的稳定标识，优先使用 DOI。
def paper_identity(paper: Paper) -> str:
    if paper.doi:
        normalized_doi = paper.doi.lower().removeprefix("https://doi.org/").removeprefix("doi:")
        return f"doi:{normalized_doi}"

    normalized_title = " ".join(paper.title.lower().split())
    return f"title:{normalized_title}|year:{paper.year or ''}"


# 按论文标识移除多平台搜索结果中的重复记录。
def deduplicate_papers(papers: list[Paper]) -> list[Paper]:
    seen: set[str] = set()
    unique_papers: list[Paper] = []

    for paper in papers:
        identity = paper_identity(paper)
        if identity in seen:
            continue
        seen.add(identity)
        unique_papers.append(paper)

    return unique_papers


# 调用指定平台的适配器，并返回统一的论文列表和命中总数。
async def search_one_platform(
    *,
    platform: str,
    keyword: str,
    page: int,
    page_size: int,
) -> tuple[list[Paper], int]:
    return await sources[platform].search(
        keyword=keyword,
        page=page,
        page_size=page_size,
    )


# 并行搜索全部平台，合并、去重并按访问能力排序结果。
async def search_all_platforms(
    *,
    keyword: str,
    page: int,
    page_size: int,
) -> tuple[list[Paper], int, list[str], list[str]]:
    platform_names = list(sources)
    # Fetch one full page from every source so access-capable records can be ranked
    # fairly before the merged UI page is capped at page_size.
    per_source_page_size = page_size
    results = await asyncio.gather(
        *(
            search_one_platform(
                platform=platform,
                keyword=keyword,
                page=page,
                page_size=per_source_page_size,
            )
            for platform in platform_names
        ),
        return_exceptions=True,
    )

    merged: list[Paper] = []
    total = 0
    searched_platforms: list[str] = []
    failed_platforms: list[str] = []

    for platform, result in zip(platform_names, results, strict=True):
        if isinstance(result, Exception):
            failed_platforms.append(platform)
            continue

        papers, platform_total = result
        searched_platforms.append(platform)
        merged.extend(papers)
        total += platform_total

    if not searched_platforms:
        raise PaperSourceError

    unique_papers = deduplicate_papers(merged)
    unique_papers.sort(key=access_priority)
    return unique_papers[:page_size], total, searched_platforms, failed_platforms


@router.get("/search", response_model=PaperSearchResponse)
# 处理论文搜索接口请求，并根据平台参数返回统一结果。
async def search_papers(
    q: str = Query(default="", description="Search keyword"),
    platform: str = Query(default="all", description="all or one supported platform"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, alias="pageSize", ge=1, le=50),
) -> PaperSearchResponse | JSONResponse:
    keyword = q.strip()
    selected_platform = platform.strip().lower()

    if not keyword:
        return error_response(
            query=keyword,
            page=page,
            page_size=page_size,
            requested_platform=selected_platform,
            code="INVALID_QUERY",
            message="搜索关键词不能为空",
            status_code=400,
        )

    if selected_platform not in available_platforms:
        return error_response(
            query=keyword,
            page=page,
            page_size=page_size,
            requested_platform=selected_platform,
            code="INVALID_PLATFORM",
            message="不支持该论文平台",
            status_code=400,
        )

    try:
        if selected_platform == "all":
            papers, total, searched_platforms, failed_platforms = await search_all_platforms(
                keyword=keyword,
                page=page,
                page_size=page_size,
            )
            total_is_approximate = True
        else:
            papers, total = await search_one_platform(
                platform=selected_platform,
                keyword=keyword,
                page=page,
                page_size=page_size,
            )
            searched_platforms = [selected_platform]
            failed_platforms = []
            total_is_approximate = False
    except PaperSourceError as exc:
        return error_response(
            query=keyword,
            page=page,
            page_size=page_size,
            requested_platform=selected_platform,
            code="PAPER_SOURCE_REQUEST_FAILED",
            message=str(exc) or "论文平台请求失败，请稍后重试",
            status_code=502,
        )

    return PaperSearchResponse(
        data=papers,
        meta=make_meta(
            query=keyword,
            page=page,
            page_size=page_size,
            total=total,
            requested_platform=selected_platform,
            searched_platforms=searched_platforms,
            total_is_approximate=total_is_approximate,
            failed_platforms=failed_platforms,
        ),
        error=None,
    )
