from pydantic import BaseModel, ConfigDict, Field


def to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class Paper(ApiModel):
    id: str
    title: str
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    source: str | None = None
    url: str
    citation_count: int | None = None
    download_count: int | None = None
    is_open_access: bool = False
    pdf_url: str | None = None


class PaperSearchMeta(ApiModel):
    query: str
    page: int
    page_size: int
    total: int
    source: str


class ApiError(ApiModel):
    code: str
    message: str


class PaperSearchResponse(ApiModel):
    data: list[Paper]
    meta: PaperSearchMeta
    error: ApiError | None = None
