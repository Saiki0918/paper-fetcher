"""验证第三方响应契约、关键词分页及跨平台结果合并；测试不访问外网。"""

import asyncio
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app.api.routes import papers as routes
from app.main import app
from app.schemas.paper import Paper
from app.sources.base import PaperSourceError
from app.sources.europepmc import EuropePmcAdapter
from app.sources.hal import HalAdapter
from app.sources.osf import OsfPreprintAdapter
from app.sources.preprints import IndexedPreprintAdapter
from app.sources.zenodo import ZenodoAdapter


# 平台标识与 Europe PMC 发布者名分开保存，便于验证每个入口的查询约束。
INDEXED_PLATFORMS = {
    "biorxiv": "bioRxiv", "medrxiv": "medRxiv",
    "chemrxiv": "ChemRxiv", "researchsquare": "Research Square",
}
NEW_PLATFORMS = [*INDEXED_PLATFORMS, "osf", "psyarxiv", "socarxiv", "hal", "zenodo"]
# 样例随测试存放，运行时不依赖用户的 Postman 导出目录或第三方网络状态。
FIXTURES = Path(__file__).parent / "fixtures" / "preprints"


def fixture(name: str) -> dict:
    """每次重新解析保存响应，允许用例修改字典且不影响后续测试。"""
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def indexed_record() -> dict:
    """构造含团体作者与免费详情链接、但没有 PDF 的最小索引记录。"""
    return {
        "id": "PPR123", "source": "PPR", "doi": "10.1234/preprint.v1",
        "title": "Machine learning", "pubYear": "2025",
        "abstractText": "<p>Methods &amp; results.</p>",
        "authorList": {"author": [{"fullName": "A. Author"}, {"collectiveName": "Study Group"}]},
        "isOpenAccess": "N",
        "fullTextUrlList": {"fullTextUrl": [{
            "availabilityCode": "F", "documentStyle": "doi",
            "url": "https://doi.org/10.1234/preprint.v1",
        }]},
    }


def osf_record() -> dict:
    """同时覆盖两种 DOI、版本化 ID、注册/未注册作者与主文件 embeds。"""
    return {
        "id": "abc_v2",
        "attributes": {
            "title": "Machine learning", "description": "<p>Summary</p>",
            "date_published": "2025-06-01", "date_withdrawn": None, "public": True,
            "doi": "10.9999/published-article",
        },
        "links": {
            "html": "https://osf.io/preprints/psyarxiv/abc_v2/",
            "preprint_doi": "https://doi.org/10.31234/osf.io/abc_v2",
        },
        "relationships": {"provider": {"data": {"id": "psyarxiv"}}},
        "embeds": {
            "primary_file": {"data": {
                "attributes": {"name": "Manuscript.PDF"},
                "links": {"download": "https://osf.io/download/file123/"},
            }},
            "bibliographic_contributors": {"data": [
                {"attributes": {}, "embeds": {"users": {"data": {
                    "attributes": {"full_name": "A. Author"},
                }}}},
                {"attributes": {"unregistered_contributor": "B. Author"}},
            ]},
        },
    }


def zenodo_record(access: str = "open") -> dict:
    """将 ZIP 放在 PDF 前，检验多附件选择以及不同访问权限的解析。"""
    return {
        "id": 123,
        "metadata": {
            "title": "Machine learning", "publication_date": "2025-01-01",
            "description": "<p>Summary &amp; methods</p>", "access_right": access,
            "creators": [{"name": "Author, Alice"}], "doi": "10.5281/zenodo.123",
        },
        "links": {"self_html": "https://zenodo.org/records/123"},
        "files": [
            {"key": "data.zip", "links": {"self": "https://zenodo.org/data.zip"}},
            {"key": "paper.pdf", "links": {"self": "https://zenodo.org/paper.pdf"}},
        ],
    }


class IndexedPreprintTests(unittest.IsolatedAsyncioTestCase):
    """确认四个发布平台共用索引流程，同时保有独立的筛选条件与展示信息。"""

    async def test_publisher_scoping_pagination_and_normalization(self):
        """OR 关键词仍整体受预印本及发布者条件约束，分页与字段清理均应保留。"""
        for platform, publisher in INDEXED_PLATFORMS.items():
            with self.subTest(platform=platform):
                payload = {"hitCount": 21, "resultList": {"result": [indexed_record()]}}
                with patch("app.sources.europepmc.request_json", new_callable=AsyncMock, return_value=payload) as request:
                    papers, total = await IndexedPreprintAdapter(platform, publisher).search(
                        keyword="machine learning OR statistics", page=2, page_size=5,
                    )
                params = request.call_args.kwargs["params"]
                self.assertEqual(params["query"], f'(machine learning OR statistics) AND SRC:PPR AND PUBLISHER:"{publisher}"')
                self.assertEqual((params["page"], params["pageSize"]), (2, 5))
                self.assertEqual(total, 21)
                paper = papers[0]
                self.assertEqual((paper.platform, paper.source), (platform, publisher))
                self.assertEqual(paper.authors, ["A. Author", "Study Group"])
                self.assertEqual(paper.abstract, "Methods & results.")
                self.assertEqual(paper.url, "https://doi.org/10.1234/preprint.v1")
                self.assertEqual(paper.access_type, "open")
                self.assertIsNone(paper.pdf_url)

    async def test_existing_europepmc_search_remains_unrestricted(self):
        """增加平台子入口后，Europe PMC 总入口仍原样搜索关键词，不自动限为预印本。"""
        with patch("app.sources.europepmc.request_json", new_callable=AsyncMock,
                   return_value={"hitCount": 0, "resultList": {"result": []}}) as request:
            papers, total = await EuropePmcAdapter().search(keyword="cancer", page=1, page_size=10)
        self.assertEqual(request.call_args.kwargs["params"]["query"], "cancer")
        self.assertEqual((papers, total), ([], 0))

    def test_explicit_pdf_and_missing_doi(self):
        """没有 DOI 时保留索引详情页，明确标记为 PDF 的无后缀下载地址仍可展示。"""
        record = indexed_record()
        record.pop("doi")
        record["fullTextUrlList"]["fullTextUrl"].append({
            "availabilityCode": "OA", "documentStyle": "pdf",
            "url": "https://example.org/download?file=123",
        })
        paper = IndexedPreprintAdapter("chemrxiv", "ChemRxiv").to_paper(record)
        self.assertEqual(paper.url, "https://europepmc.org/article/PPR/PPR123")
        self.assertEqual(paper.access_type, "openPdf")
        self.assertEqual(paper.pdf_url, "https://example.org/download?file=123")


class ChemRxivPdfTests(unittest.TestCase):
    """复现检索 API 仍提供失效代理地址的情况，确保不换错论文或预印本版本。"""

    def test_expired_proxy_is_replaced_in_both_local_search_entries(self):
        """回放失效代理样例，两个搜索入口均应改用保留完整版本 DOI 的 ChemRxiv 地址。"""
        raw = fixture("chemrxiv-expired-proxy")
        proxy = raw["resultList"]["result"][0]["fullTextUrlList"]["fullTextUrl"][-1]["url"]
        self.assertEqual(proxy, "https://europepmc.org/api/fulltextRepo?pprId=PPR300229&type=FILE&fileName=EMS120324-pdf.pdf&mimeType=application/pdf")
        client = TestClient(app)
        for platform in ("europepmc", "chemrxiv"):
            with self.subTest(platform=platform):
                with patch("app.sources.europepmc.request_json", new_callable=AsyncMock, return_value=raw) as request:
                    response = client.get("/api/papers/search", params={
                        "q": "EXT_ID:PPR300229", "platform": platform,
                    })
                self.assertEqual(response.status_code, 200)
                paper = response.json()["data"][0]
                self.assertEqual(paper["doi"], "10.26434/chemrxiv.12915779.v3")
                self.assertEqual(paper["pdfUrl"], "https://chemrxiv.org/doi/pdf/10.26434/chemrxiv.12915779.v3")
                self.assertEqual(paper["accessType"], "openPdf")
                request.assert_awaited_once()

    def test_explicit_external_pdf_is_preferred_over_a_proxy_appearing_first(self):
        """候选数组中代理排在前面时，仍优先保留 API 明确给出的外部 PDF。"""
        record = next(row for row in fixture("chemrxiv")["resultList"]["result"] if row["id"] == "PPR213034")
        links = record["fullTextUrlList"]["fullTextUrl"]
        expected = links[0]["url"]
        links.insert(0, {
            "availabilityCode": "OA", "documentStyle": "pdf",
            "url": "https://europepmc.org/api/fulltextRepo?pprId=PPR213034&type=FILE",
        })
        self.assertEqual(EuropePmcAdapter.to_paper(record).pdf_url, expected)

    def test_chemrxiv_doi_only_records_use_the_native_doi_route(self):
        """索引只有 ChemRxiv DOI 时，使用完整 DOI 对应的原站 PDF 路由。"""
        record = fixture("chemrxiv")["resultList"]["result"][1]
        self.assertEqual(EuropePmcAdapter.to_paper(record).pdf_url,
                         f"https://chemrxiv.org/doi/pdf/{record['doi']}")

    def test_chemrxiv_replacement_does_not_apply_to_other_platforms_or_formal_articles(self):
        """ChemRxiv 代理替换规则不能误用于其他预印本 DOI 或正式论文记录。"""
        for source, doi in [("PPR", "10.64898/2026.09.08.750034"),
                            ("PPR", "10.1101/2025.01.01.123456"),
                            ("PPR", "10.21203/rs.3.rs-123456/v1"),
                            ("MED", "10.26434/chemrxiv.12915779.v3")]:
            with self.subTest(source=source, doi=doi):
                record = fixture("chemrxiv-expired-proxy")["resultList"]["result"][0]
                record.update(source=source, doi=doi)
                proxy = record["fullTextUrlList"]["fullTextUrl"][-1]["url"]
                self.assertEqual(EuropePmcAdapter.to_paper(record).pdf_url, proxy)

    def test_existing_pmc_pdf_fallback_remains_available(self):
        """PMC 身份与 hasPDF 均明确时，原有的标准 PDF 入口仍可生成。"""
        record = indexed_record()
        record.update(source="MED", pmcid="PMC123456", hasPDF="Y")
        self.assertEqual(EuropePmcAdapter.to_paper(record).pdf_url,
                         "https://pmc.ncbi.nlm.nih.gov/articles/PMC123456/pdf/")


class OsfTests(unittest.IsolatedAsyncioTestCase):
    """分别验证 OSF 基础检索、关联元数据补查，以及公共文件的展示条件。"""

    async def test_provider_title_search_pagination_and_metadata(self):
        """合集和社区使用各自接口，正确传递标题与分页，并复用已有 embeds。"""
        payload = {"data": [osf_record()], "links": {"meta": {"total": 31}}}
        for provider in (None, "psyarxiv", "socarxiv"):
            with self.subTest(provider=provider):
                with patch("app.sources.osf.request_json", new_callable=AsyncMock, return_value=payload) as request:
                    papers, total = await OsfPreprintAdapter(provider).search(
                        keyword="machine learning", page=3, page_size=5,
                    )
                params = request.call_args.kwargs["params"]
                self.assertEqual(params["filter[title]"], "machine learning")
                expected_endpoint = (
                    f"https://api.osf.io/v2/providers/preprints/{provider}/preprints/"
                    if provider else "https://api.osf.io/v2/preprints/"
                )
                self.assertEqual(request.call_args.args[0], expected_endpoint)
                self.assertEqual((params["page"], params["page[size]"]), (3, 5))
                self.assertNotIn("embed", params)
                self.assertNotIn("filter[provider]", params)
                self.assertEqual(total, 31)
                self.assertEqual(papers[0].platform, provider or "osf")
                self.assertEqual(papers[0].authors, ["A. Author", "B. Author"])
                self.assertEqual(papers[0].doi, "10.31234/osf.io/abc_v2")
                self.assertEqual(papers[0].access_type, "openPdf")

    async def test_basic_search_enriches_from_real_relationships_and_encodes_params_once(self):
        """用实际样例关系链接补齐作者和 PDF，同时确认方括号参数只编码一次。"""
        requests: list[httpx.Request] = []

        def respond(request: httpx.Request) -> httpx.Response:
            # 按真实请求路径分别回放基础列表、主文件和署名作者，保留 HTTP 编码行为。
            requests.append(request)
            if request.url.path == "/v2/preprints/":
                return httpx.Response(200, json=fixture("osf-search"))
            if "/files/" in request.url.path:
                return httpx.Response(200, json=fixture("osf-file"))
            return httpx.Response(200, json=fixture("osf-authors"))

        # 经过真实 request_json 和 httpx 编码，只替换网络传输层。
        def client(**kwargs):
            return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

        with patch("app.core.http_client.create_http_client", side_effect=client), \
             patch("app.sources.osf.create_http_client", side_effect=client):
            papers, total = await OsfPreprintAdapter().search(keyword="machine learning", page=1, page_size=1)
        search_request = requests[0]
        self.assertEqual(search_request.url.params["page[size]"], "1")
        self.assertIn("page%5Bsize%5D=1", str(search_request.url))
        self.assertNotIn("%255B", str(search_request.url))
        self.assertNotIn("embed", search_request.url.params)
        self.assertEqual(len(requests), 3)
        self.assertEqual(total, 918)
        self.assertEqual(papers[0].authors, ["Muwon Kwon", "Peter M. Steiner"])
        self.assertEqual(papers[0].pdf_url, "https://osf.io/download/6ad1994456e0470ec724075c/")
        self.assertEqual(papers[0].access_type, "openPdf")
        self.assertIsNone(papers[0].citation_count)

    async def test_metadata_502_preserves_search_results_and_the_successful_pdf(self):
        """作者接口返回 502 时，已成功取得的 PDF 与基础搜索总数仍应返回。"""
        record = fixture("osf-search")["data"][0]
        response = httpx.Response(502, request=httpx.Request("GET", OsfPreprintAdapter.endpoint))

        async def request(url, **kwargs):
            if url == OsfPreprintAdapter.endpoint:
                return {"data": [record], "links": {"meta": {"total": 1}}}
            if "/files/" in url:
                return fixture("osf-file")
            response.raise_for_status()

        with patch("app.sources.osf.request_json", side_effect=request):
            papers, total = await OsfPreprintAdapter().search(keyword="test", page=1, page_size=1)
        self.assertEqual(total, 1)
        self.assertEqual(papers[0].authors, [])
        self.assertIsNotNone(papers[0].pdf_url)

    async def test_metadata_budget_cancels_pending_requests_but_preserves_completed_fields(self):
        """整批超时会取消慢作者接口，但不抹去已完成的主文件补查结果。"""
        cancelled = asyncio.Event()

        async def request(url, **kwargs):
            if url == OsfPreprintAdapter.endpoint:
                return fixture("osf-search")
            if "/files/" in url:
                return fixture("osf-file")
            # 作者请求故意挂起，取消标记用于区分主动取消与仅提前返回。
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        adapter = OsfPreprintAdapter()
        adapter.metadata_budget_seconds = 0.02
        with patch("app.sources.osf.request_json", side_effect=request):
            papers, _ = await adapter.search(keyword="test", page=1, page_size=1)
        self.assertTrue(cancelled.is_set())
        self.assertIsNotNone(papers[0].pdf_url)
        self.assertEqual(papers[0].authors, [])

    async def test_contributor_pagination_preserves_all_names(self):
        """预先提供主文件，仅补查两页作者，确认 next 对象和跨页姓名累积正确。"""
        record = fixture("osf-search")["data"][0]
        record["embeds"] = {"primary_file": fixture("osf-file")}
        authors = fixture("osf-authors")
        first = {"data": authors["data"][:1], "links": {"next": {
            "href": "https://api.osf.io/v2/preprints/7hcjw_v2/bibliographic_contributors/?page=2",
        }}}
        second = {"data": authors["data"][1:], "links": {"next": None}}
        with patch("app.sources.osf.request_json", new_callable=AsyncMock,
                   side_effect=[{"data": [record]}, first, second]) as request:
            papers, _ = await OsfPreprintAdapter().search(keyword="test", page=1, page_size=1)
        self.assertEqual(request.await_count, 3)
        self.assertEqual(papers[0].authors, ["Muwon Kwon", "Peter M. Steiner"])

    async def test_metadata_rate_limit_stops_queued_requests(self):
        """关联接口收到 429 后不再发送其他排队任务，基础论文仍保留。"""
        response = httpx.Response(429, request=httpx.Request("GET", OsfPreprintAdapter.endpoint))
        error = httpx.HTTPStatusError("rate limited", request=response.request, response=response)
        adapter = OsfPreprintAdapter()
        # 串行化补查，使第二个关联任务在首个限流响应之后才获得执行机会。
        adapter.metadata_concurrency = 1
        with patch("app.sources.osf.request_json", new_callable=AsyncMock,
                   side_effect=[fixture("osf-search"), error]) as request:
            papers, _ = await adapter.search(keyword="test", page=1, page_size=1)
        self.assertEqual(request.await_count, 2)
        self.assertEqual(len(papers), 1)

    async def test_html_502_from_basic_search_is_a_source_error_not_an_empty_success(self):
        """基础检索的 HTML 网关错误必须作为来源失败上报，不能伪装为正常零命中。"""
        response = httpx.Response(502, text=(FIXTURES / "osf-502.html").read_text(encoding="utf-8"),
                                  request=httpx.Request("GET", OsfPreprintAdapter.endpoint))
        error = httpx.HTTPStatusError("bad gateway", request=response.request, response=response)
        with patch("app.sources.osf.request_json", new_callable=AsyncMock, side_effect=error) as request:
            with self.assertRaisesRegex(PaperSourceError, "HTTP 502"):
                await OsfPreprintAdapter().search(keyword="test", page=1, page_size=1)
        self.assertEqual(request.await_count, 1)

    async def test_rate_limit_is_not_retried(self):
        """基础搜索被限流时直接报告来源错误，本适配层不重复请求。"""
        response = httpx.Response(429, request=httpx.Request("GET", OsfPreprintAdapter.endpoint))
        error = httpx.HTTPStatusError("rate limited", request=response.request, response=response)
        with patch("app.sources.osf.request_json", new_callable=AsyncMock, side_effect=error) as request:
            with self.assertRaises(PaperSourceError):
                await OsfPreprintAdapter().search(keyword="test", page=1, page_size=1)
        self.assertEqual(request.await_count, 1)

    def test_docx_is_not_exposed_as_pdf(self):
        """主文件存在下载地址但格式为 DOCX 时，只保留开放状态。"""
        record = osf_record()
        record["embeds"]["primary_file"]["data"]["attributes"]["name"] = "paper.docx"
        paper = OsfPreprintAdapter().to_paper(record)
        self.assertIsNone(paper.pdf_url)
        self.assertEqual(paper.access_type, "open")

    def test_withdrawn_record_has_no_public_pdf(self):
        """已撤回记录不能因仍保留文件元数据而显示公开 PDF。"""
        record = osf_record()
        record["attributes"]["date_withdrawn"] = "2025-07-01"
        paper = OsfPreprintAdapter().to_paper(record)
        self.assertFalse(paper.is_open_access)
        self.assertIsNone(paper.pdf_url)

    def test_nonpublic_record_has_no_pdf(self):
        """非公开记录即使含有主文件 embeds，也不展示 PDF 阅读按钮。"""
        record = osf_record()
        record["attributes"]["public"] = False
        self.assertIsNone(OsfPreprintAdapter().to_paper(record).pdf_url)

    def test_published_doi_is_not_used_as_preprint_doi(self):
        """缺少预印本 DOI 时，不借用 attributes.doi 中关联的正式出版物 DOI。"""
        record = osf_record()
        record["links"].pop("preprint_doi")
        self.assertIsNone(OsfPreprintAdapter().to_paper(record).doi)


class RepositoryTests(unittest.IsolatedAsyncioTestCase):
    """覆盖综合仓储的文献类型限制、分页差异、文件权限与异常响应处理。"""

    async def test_hal_limits_document_type_and_uses_offset(self):
        """HAL 限定工作论文类型，将页码转为偏移量，并规范多语言字段与主文件链接。"""
        payload = {"response": {"numFound": 42, "docs": [{
            "halId_s": "hal-123", "title_s": ["A paper", "Un article"],
            "authFullName_s": ["A. Author"], "abstract_s": ["<p>A summary</p>"],
            "doiId_s": "10.1234/test", "producedDateY_i": 2025,
            "uri_s": "https://hal.science/hal-123v1", "openAccess_bool": True,
            "fileMain_s": "https://hal.science/hal-123/document",
        }]}}
        with patch("app.sources.hal.request_json", new_callable=AsyncMock, return_value=payload) as request:
            papers, total = await HalAdapter().search(keyword="machine learning", page=3, page_size=5)
        params = request.call_args.kwargs["params"]
        self.assertEqual((params["q"], params["fq"]), ("machine learning", "docType_s:UNDEFINED"))
        self.assertEqual((params["start"], params["rows"]), (10, 5))
        self.assertEqual(total, 42)
        self.assertEqual((papers[0].title, papers[0].abstract), ("A paper", "A summary"))
        self.assertEqual(papers[0].access_type, "openPdf")

    async def test_zenodo_limits_resource_type_and_handles_both_total_formats(self):
        """Zenodo 同时限定 publication/preprint，并兼容整数和对象两种总数格式。"""
        for raw_total in (42, {"value": 42, "relation": "eq"}):
            with self.subTest(raw_total=raw_total):
                with patch("app.sources.zenodo.request_json", new_callable=AsyncMock,
                           return_value={"hits": {"total": raw_total, "hits": [zenodo_record()]}}) as request:
                    papers, total = await ZenodoAdapter().search(keyword="machine learning", page=2, page_size=5)
                params = request.call_args.kwargs["params"]
                self.assertEqual((params["type"], params["subtype"]), ("publication", "preprint"))
                self.assertEqual((params["page"], params["size"]), (2, 5))
                self.assertEqual(total, 42)
                self.assertEqual(papers[0].pdf_url, "https://zenodo.org/paper.pdf")
                self.assertEqual(papers[0].abstract, "Summary & methods")

    def test_zenodo_restricted_and_embargoed_files_have_no_pdf_button(self):
        """受限、禁运和关闭的记录即使含 PDF 元数据，也不暴露可下载状态。"""
        for access in ("restricted", "embargoed", "closed"):
            with self.subTest(access=access):
                paper = ZenodoAdapter().to_paper(zenodo_record(access))
                self.assertIsNone(paper.pdf_url)
                self.assertEqual(paper.access_type, "detail")

    def test_zenodo_null_optional_metadata(self):
        """作者和文件为 null 时返回空作者及缺失 PDF，而不是抛出解析异常。"""
        record = zenodo_record()
        record["metadata"]["creators"] = None
        record["files"] = None
        paper = ZenodoAdapter().to_paper(record)
        self.assertEqual(paper.authors, [])
        self.assertIsNone(paper.pdf_url)

    async def test_empty_and_malformed_responses(self):
        """合法空列表应返回零命中，缺失列表或错误对象则统一抛出来源异常。"""
        cases = [
            (HalAdapter(), "app.sources.hal.request_json", {"response": {"numFound": 0, "docs": []}}),
            (ZenodoAdapter(), "app.sources.zenodo.request_json", {"hits": {"total": 0, "hits": []}}),
            (OsfPreprintAdapter(), "app.sources.osf.request_json", {"data": [], "links": {"meta": {"total": 0}}}),
            (IndexedPreprintAdapter("biorxiv", "bioRxiv"), "app.sources.europepmc.request_json",
             {"hitCount": 0, "resultList": {"result": []}}),
        ]
        for adapter, target, empty in cases:
            with self.subTest(adapter=adapter.name):
                with patch(target, new_callable=AsyncMock, return_value=empty):
                    self.assertEqual(await adapter.search(keyword="none", page=1, page_size=5), ([], 0))
                for invalid in ({}, [], {"error": "upstream unavailable"}):
                    with patch(target, new_callable=AsyncMock, return_value=invalid):
                        with self.assertRaises(PaperSourceError):
                            await adapter.search(keyword="test", page=1, page_size=5)


class PostmanResponseTests(unittest.TestCase):
    """用用户的六份成功响应验证实际边界；fixture 不依赖仓库外的原始目录。"""

    def test_all_six_saved_responses_reach_the_local_api_with_expected_pdf_counts(self):
        """仅凭保存的搜索响应核对六个平台的 PDF 数量、字段类型及引用量缺失语义。"""
        expected_pdf_ids = {
            "biorxiv": set(), "medrxiv": set(), "researchsquare": set(),
            "chemrxiv": {f"chemrxiv:{row['id']}" for row in fixture("chemrxiv")["resultList"]["result"]},
            "hal": {"hal:hal-01822073", "hal:hal-04373389", "hal:hal-01817270", "hal:hal-04972099"},
            "zenodo": {"zenodo:18260899", "zenodo:21509145", "zenodo:16566059"},
        }
        client = TestClient(app)
        for platform, expected in expected_pdf_ids.items():
            with self.subTest(platform=platform):
                module = "europepmc" if platform in INDEXED_PLATFORMS else platform
                # 本测试只回放搜索 JSON；原站补查契约由独立测试及其真实样例验证。
                with patch(f"app.sources.{module}.request_json", new_callable=AsyncMock,
                           return_value=fixture(platform)), \
                     patch("app.sources.preprint_pdf.request_json", new_callable=AsyncMock, return_value={}), \
                     patch("app.sources.preprint_pdf.request_content", new_callable=AsyncMock, return_value=b""):
                    response = client.get("/api/papers/search", params={
                        "q": "machine learning", "platform": platform, "pageSize": 5,
                    })
                self.assertEqual(response.status_code, 200)
                rows = response.json()["data"]
                self.assertEqual(len(rows), 5)
                self.assertEqual({row["id"] for row in rows if row["pdfUrl"]}, expected)
                for row in rows:
                    self.assertEqual(row["citationCount"], 0 if platform in INDEXED_PLATFORMS else None)
                    self.assertIsInstance(row["authors"], list)
                    if row["pdfUrl"]:
                        self.assertEqual(row["accessType"], "openPdf")

    def test_europepmc_and_filtered_views_agree_on_free_access_and_original_source(self):
        """同一索引记录从总入口与平台入口解析时，来源名、免费状态和 PDF 应保持一致。"""
        for platform, publisher in INDEXED_PLATFORMS.items():
            for record in fixture(platform)["resultList"]["result"]:
                with self.subTest(platform=platform, record=record["id"]):
                    general = EuropePmcAdapter.to_paper(record)
                    filtered = IndexedPreprintAdapter(platform, publisher).to_paper(record)
                    self.assertEqual(general.source, publisher)
                    self.assertEqual(general.is_open_access, filtered.is_open_access)
                    self.assertEqual(general.access_type, filtered.access_type)
                    self.assertEqual(general.pdf_url, filtered.pdf_url)
                    self.assertTrue(general.is_open_access)

    def test_explicit_chemrxiv_pdf_is_kept_even_when_has_pdf_is_n(self):
        """hasPDF=N 不能否定全文列表中明确给出的外部 PDF 地址。"""
        record = next(row for row in fixture("chemrxiv")["resultList"]["result"] if row["id"] == "PPR213034")
        self.assertEqual((record["hasPDF"], record["isOpenAccess"]), ("N", "N"))
        paper = EuropePmcAdapter.to_paper(record)
        self.assertTrue(paper.pdf_url.endswith("machine-learning.pdf"))
        self.assertEqual(paper.access_type, "openPdf")

    def test_zero_missing_and_string_citations_are_distinct(self):
        """真实零引用、数字字符串和缺失值分别解析，布尔值不得误计为整数引用量。"""
        record = fixture("chemrxiv")["resultList"]["result"][0]
        self.assertIn("commentCorrectionList", record)
        for raw, expected in [(0, 0), ("17", 17), (None, None), (True, None)]:
            with self.subTest(raw=raw):
                changed = copy.deepcopy(record)
                changed["citedByCount"] = raw
                self.assertEqual(EuropePmcAdapter.to_paper(changed).citation_count, expected)
        record.pop("citedByCount")
        self.assertIsNone(EuropePmcAdapter.to_paper(record).citation_count)

    def test_zenodo_zip_only_records_and_encoded_pdf_links_are_preserved(self):
        """仅含 ZIP 的开放记录不显示 PDF，含特殊字符的官方下载链接原样保留。"""
        records = {str(row["id"]): row for row in fixture("zenodo")["hits"]["hits"]}
        for record_id in ("22238050", "22235275"):
            paper = ZenodoAdapter.to_paper(records[record_id])
            self.assertIsNone(paper.pdf_url)
            self.assertIsNone(paper.citation_count)
            self.assertEqual(paper.access_type, "open")
        record = records["18260899"]
        expected = next(file["links"]["self"] for file in record["files"] if file["key"].endswith(".pdf"))
        self.assertIn("%C3%B1", expected)
        self.assertEqual(ZenodoAdapter.to_paper(record).pdf_url, expected)

    def test_new_biorxiv_doi_prefix_and_collective_authors_are_supported(self):
        """实际样例中的新 bioRxiv DOI 前缀与 medRxiv 团体作者均应完整保留。"""
        bio = IndexedPreprintAdapter("biorxiv", "bioRxiv").to_paper(fixture("biorxiv")["resultList"]["result"][0])
        self.assertEqual(bio.doi, "10.64898/2026.09.08.750034")
        med = IndexedPreprintAdapter("medrxiv", "medRxiv").to_paper(fixture("medrxiv")["resultList"]["result"][0])
        self.assertEqual(len(med.authors), 9)

    def test_hal_multilingual_arrays_and_xml_abstract_are_normalized(self):
        """实际 HAL 的多语言数组与 XML 摘要规范为文本，年份和引用量缺失语义不变。"""
        for record in fixture("hal")["response"]["docs"]:
            paper = HalAdapter.to_paper(record)
            self.assertIsInstance(paper.title, str)
            self.assertNotIn("<", paper.abstract or "")
            self.assertIsInstance(paper.year, int)
            self.assertIsNone(paper.citation_count)


class SearchRouteTests(unittest.TestCase):
    """通过本地 HTTP 接口验证新平台注册、参数传递、合并去重与错误响应。"""

    def setUp(self):
        self.client = TestClient(app)

    def test_all_new_platforms_are_registered_and_accepted(self):
        """逐个平台确认路由接受标识，并将关键词、页码和大小传给对应适配器。"""
        for platform in NEW_PLATFORMS:
            with self.subTest(platform=platform):
                source = routes.sources[platform]
                paper = Paper(id=f"{platform}:123", platform=platform, title="Test", url="https://example.org")
                with patch.object(source, "search", new_callable=AsyncMock, return_value=([paper], 1)) as search:
                    response = self.client.get("/api/papers/search", params={
                        "q": "machine learning", "platform": platform, "page": 2, "pageSize": 5,
                    })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["meta"]["searchedPlatforms"], [platform])
                self.assertEqual(response.json()["data"][0]["platform"], platform)
                search.assert_awaited_once_with(keyword="machine learning", page=2, page_size=5)

    def test_all_search_deduplicates_and_keeps_better_access_despite_a_failed_source(self):
        """多个来源命中相同 DOI 时保留更易访问的记录，单源故障仅进入失败平台列表。"""
        indexed = Paper(id="europepmc:123", platform="europepmc", title="Test", doi="10.1234/test",
                        url="https://example.org")
        direct = indexed.model_copy(update={"id": "biorxiv:123", "platform": "biorxiv",
                                            "pdf_url": "https://example.org/test.pdf", "is_open_access": True})
        # 将缺少 PDF 的重复记录放在前面，验证合并流程确实先排序再去重。
        sources = {
            "europepmc": AsyncMock(search=AsyncMock(return_value=([indexed], 1))),
            "biorxiv": AsyncMock(search=AsyncMock(return_value=([direct], 1))),
            "osf": AsyncMock(search=AsyncMock(side_effect=PaperSourceError("unavailable"))),
        }
        with patch.object(routes, "sources", sources):
            response = self.client.get("/api/papers/search", params={"q": "test", "platform": "all"})
        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload["data"]), 1)
        self.assertEqual(payload["data"][0]["platform"], "biorxiv")
        self.assertEqual(payload["meta"]["failedPlatforms"], ["osf"])
        self.assertTrue(payload["meta"]["totalIsApproximate"])

    def test_single_platform_failure_and_invalid_platform(self):
        """单平台上游失败返回统一 502；未注册的平台参数在本地校验为 400。"""
        with patch.object(routes.sources["zenodo"], "search", new_callable=AsyncMock,
                          side_effect=PaperSourceError("rate limited")):
            response = self.client.get("/api/papers/search", params={"q": "test", "platform": "zenodo"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "PAPER_SOURCE_REQUEST_FAILED")
        response = self.client.get("/api/papers/search", params={"q": "test", "platform": "unknown"})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
