from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.schemas.paper import ApiError, PaperSearchMeta, PaperSearchResponse
from app.sources.openalex import OpenAlexAdapter, OpenAlexError

router = APIRouter(prefix="/api/papers", tags=["papers"])
openalex = OpenAlexAdapter()


def error_response(
    *,
    query: str,
    page: int,
    page_size: int,
    code: str,
    message: str,
    status_code: int,
) -> JSONResponse:
    payload = PaperSearchResponse(
        data=[],
        meta=PaperSearchMeta(
            query=query,
            page=page,
            page_size=page_size,
            total=0,
            source="openalex",
        ),
        error=ApiError(code=code, message=message),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(by_alias=True))


@router.get("/search", response_model=PaperSearchResponse)
async def search_papers(
    q: str = Query(default="", description="Search keyword"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, alias="pageSize", ge=1, le=50),
) -> PaperSearchResponse | JSONResponse:
    keyword = q.strip()
    if not keyword:
        return error_response(
            query=keyword,
            page=page,
            page_size=page_size,
            code="INVALID_QUERY",
            message="搜索关键词不能为空",
            status_code=400,
        )

    try:
        papers, total = await openalex.search(
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
    except OpenAlexError:
        return error_response(
            query=keyword,
            page=page,
            page_size=page_size,
            code="OPENALEX_REQUEST_FAILED",
            message="OpenAlex 请求失败，请稍后重试",
            status_code=502,
        )

    return PaperSearchResponse(
        data=papers,
        meta=PaperSearchMeta(
            query=keyword,
            page=page,
            page_size=page_size,
            total=total,
            source="openalex",
        ),
        error=None,
    )
