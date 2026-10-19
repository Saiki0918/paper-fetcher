import asyncio
import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.schemas.paper import ApiError, Paper, PaperSearchMeta, PaperSearchResponse
from app.sources.arxiv import ArxivAdapter
from app.sources.base import PaperSource, PaperSourceError, access_priority
from app.sources.crossref import CrossrefAdapter
from app.sources.dblp import DblpAdapter
from app.sources.doaj import DoajAdapter
from app.sources.europepmc import EuropePmcAdapter
from app.sources.hal import HalAdapter
from app.sources.openalex import OpenAlexAdapter
from app.sources.osf import OsfPreprintAdapter
from app.sources.preprints import IndexedPreprintAdapter
from app.sources.pubmed import PubMedAdapter
from app.sources.zenodo import ZenodoAdapter

router = APIRouter(prefix="/api/papers", tags=["papers"])
logger = logging.getLogger(__name__)

# 注册表键是前端提交的稳定平台标识；适配器负责各自的查询规则和字段转换。
sources: dict[str, PaperSource] = {
    "openalex": OpenAlexAdapter(),
    "crossref": CrossrefAdapter(),
    "arxiv": ArxivAdapter(),
    "europepmc": EuropePmcAdapter(),
    "pubmed": PubMedAdapter(),
    "dblp": DblpAdapter(),
    "doaj": DoajAdapter(),
    # 四个平台通过 Europe PMC 的预印本索引提供关键词搜索。
    "biorxiv": IndexedPreprintAdapter("biorxiv", "bioRxiv"),
    "medrxiv": IndexedPreprintAdapter("medrxiv", "medRxiv"),
    "chemrxiv": IndexedPreprintAdapter("chemrxiv", "ChemRxiv"),
    "researchsquare": IndexedPreprintAdapter("researchsquare", "Research Square"),
    # OSF 合集与两个独立社区共用适配器，社区范围由 provider 专属接口限定。
    "osf": OsfPreprintAdapter(),
    "psyarxiv": OsfPreprintAdapter("psyarxiv", "PsyArXiv"),
    "socarxiv": OsfPreprintAdapter("socarxiv", "SocArXiv"),
    # 综合仓储按官方文献类型筛选预印本，避免混入期刊论文、数据集或软件记录。
    "hal": HalAdapter(),
    "zenodo": ZenodoAdapter(),
}
# 参数校验和接口文档共用注册表，新增来源后无需另行维护一份后端白名单。
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
    # 每个来源各取一整页，合并排序后才截取展示页，避免某来源过早被分配更少名额。
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
        # 单个来源失败作为结果收集，允许其他平台的成功论文继续返回。
        return_exceptions=True,
    )

    merged: list[Paper] = []
    total = 0
    searched_platforms: list[str] = []
    failed_platforms: list[str] = []

    for platform, result in zip(platform_names, results, strict=True):
        if isinstance(result, Exception):
            failed_platforms.append(platform)
            # 保留服务端日志中的平台和原始异常，便于定位 502 的真实原因。
            logger.warning("论文平台 %s 搜索失败: %s", platform, result, exc_info=result)
            continue

        papers, platform_total = result
        searched_platforms.append(platform)
        merged.extend(papers)
        # 总数来自各源命中数相加，存在索引/原平台重叠，因此全平台搜索标记为近似值。
        total += platform_total

    if not searched_platforms:
        details = "; ".join(
            f"{platform}: {result}"
            for platform, result in zip(platform_names, results, strict=True)
            if isinstance(result, Exception)
        )
        raise PaperSourceError(f"所有论文平台请求均失败。{details}")

    # 同一预印本可能来自聚合索引和原平台；先排序，去重时保留访问能力更好的版本。
    unique_papers = deduplicate_papers(sorted(merged, key=access_priority))
    # 这里只合并各源当前页，截取后不额外拉取下一页来补足展示数量。
    return unique_papers[:page_size], total, searched_platforms, failed_platforms


@router.get("/search", response_model=PaperSearchResponse)
# 处理论文搜索接口请求，并根据平台参数返回统一结果。
async def search_papers(
    q: str = Query(default="", description="Search keyword"),
    platform: str = Query(default="all", description=f"Supported platforms: {', '.join(available_platforms)}"),
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
        # 单平台失败会在这里留下请求参数和异常信息，方便与适配器日志对应。
        logger.exception(
            "论文搜索失败：platform=%s, page=%s, pageSize=%s",
            selected_platform,
            page,
            page_size,
        )
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
