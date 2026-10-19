"""以实际原站响应验证 PDF 补查；所有网络传输都被替换，测试不访问外网。"""

import asyncio
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.sources.europepmc import EuropePmcAdapter
from app.sources.preprint_pdf import PreprintPdfEnricher, ResearchSquarePdfResolver, RxivPdfResolver

# 固定保存的官方 JSON 和原文 HTML 让平台版本与下载链接校验可离线复现。
FIXTURES = Path(__file__).parent / "fixtures" / "preprints"


def fixture(name):
    """重新加载样例，避免测试对返回字典的修改污染其他用例。"""
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def record(platform):
    """提取平台样例中的首条索引记录，作为原站补查的输入。"""
    return fixture(platform)["resultList"]["result"][0]


class OriginalPlatformPdfTests(unittest.IsolatedAsyncioTestCase):
    """核对原站补查的身份、版本、时间预算及失败降级规则。"""

    async def test_original_metadata_supplements_both_search_entries(self):
        """Europe PMC 总入口与平台筛选入口应补齐相同 PDF，并保留原 DOI 与引用统计。"""
        for platform in ("biorxiv", "medrxiv", "researchsquare"):
            raw = record(platform)
            expected = (f"https://www.{platform}.org/content/{raw['doi']}v1.full.pdf"
                        if platform != "researchsquare" else
                        "https://www.researchsquare.com/article/rs-11017119/v1.pdf?c=1789519726000")
            requests = []

            def respond(request):
                # Rxiv 回放官方明细，Research Square 回放带 DOI 和下载按钮的版本页面。
                requests.append(request)
                if platform == "researchsquare":
                    return httpx.Response(200, content=(FIXTURES / "researchsquare-page.html").read_bytes())
                return httpx.Response(200, json=fixture(f"{platform}-details"))

            def client(**kwargs):
                # 只替换传输层，仍经过正式的 HTTP 请求、状态检查与响应解析流程。
                return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

            for entry in ("europepmc", platform):
                with self.subTest(platform=platform, entry=entry):
                    with patch("app.sources.europepmc.request_json", new_callable=AsyncMock,
                               return_value={"hitCount": 1, "resultList": {"result": [raw]}}), \
                         patch("app.sources.preprint_pdf.create_http_client", side_effect=client):
                        # TestClient 在独立事件循环中运行，测试经过实际路由和 HTTP 字段序列化。
                        response = TestClient(app).get("/api/papers/search", params={"q": "test", "platform": entry})
                    self.assertEqual(response.status_code, 200)
                    paper = response.json()["data"][0]
                    self.assertEqual(paper["pdfUrl"], expected)
                    self.assertEqual(paper["doi"], raw["doi"])
                    self.assertEqual(paper["citationCount"], 0)
                    self.assertEqual(paper["accessType"], "openPdf")
            self.assertEqual(len(requests), 2)
            self.assertIn("/v1" if platform == "researchsquare" else f"/details/{platform}/", requests[0].url.path)

    async def test_rxiv_checks_server_doi_and_version_instead_of_guessing_v1(self):
        """多版本时按明确版本或日期匹配，拒绝 DOI、站点、撤回状态等不一致的明细。"""
        raw = record("biorxiv")
        payload = fixture("biorxiv-details")
        original = payload["collection"][0]
        v2 = dict(original, version="2", date="2026-10-01")
        payload["collection"] = [v2, original]
        # 故意把新版放在前面，确保实现不会按 API 数组顺序默认选最新版。
        resolver = RxivPdfResolver("biorxiv")
        async with httpx.AsyncClient() as client:
            with patch("app.sources.preprint_pdf.request_json", new_callable=AsyncMock, return_value=payload):
                raw["versionNumber"] = 1
                self.assertTrue((await resolver.resolve(raw, client)).endswith("v1.full.pdf"))
                raw["versionNumber"] = 2
                self.assertTrue((await resolver.resolve(raw, client)).endswith("v2.full.pdf"))
                raw["versionNumber"] = 3
                self.assertIsNone(await resolver.resolve(raw, client))
                raw.pop("versionNumber")
                self.assertIsNone(await resolver.resolve(raw, client))
                raw["firstPublicationDate"] = original["date"]
                self.assertTrue((await resolver.resolve(raw, client)).endswith("v1.full.pdf"))
                raw["doi"] = original["doi"] + "v2"
                self.assertTrue((await resolver.resolve(raw, client)).endswith("v2.full.pdf"))
                raw["versionNumber"] = 1
                self.assertIsNone(await resolver.resolve(raw, client))

            raw = record("biorxiv")
            for field, value in (("server", "medRxiv"), ("doi", "10.1101/other"), ("version", "unknown"), ("type", "withdrawn")):
                changed = copy.deepcopy(fixture("biorxiv-details"))
                changed["collection"][0][field] = value
                with self.subTest(field=field), patch("app.sources.preprint_pdf.request_json", new_callable=AsyncMock, return_value=changed):
                    self.assertIsNone(await resolver.resolve(raw, client))

    async def test_unknown_sources_and_existing_pdfs_do_not_trigger_original_requests(self):
        """未知发布者、正式论文及已有明确 PDF 的记录都不应触发额外补查。"""
        raw = record("biorxiv")
        raw["bookOrReportDetails"]["publisher"] = "Unknown"
        formal = record("biorxiv")
        formal["source"] = "MED"
        existing = record("medrxiv")
        records = [raw, formal, existing]
        papers = [EuropePmcAdapter.to_paper(row) for row in records]
        papers[-1] = papers[-1].model_copy(update={"pdf_url": "https://example.org/original.pdf"})
        with patch("app.sources.preprint_pdf.create_http_client") as client:
            await PreprintPdfEnricher().enrich(records, papers)
        client.assert_not_called()
        self.assertEqual(papers[-1].pdf_url, "https://example.org/original.pdf")

    async def test_researchsquare_rejects_latest_other_versions_and_unrelated_pdf_links(self):
        """页面版本、声明的 DOI、下载域名或页面内容不匹配时，不返回候选 PDF。"""
        raw = record("researchsquare")
        page = (FIXTURES / "researchsquare-page.html").read_bytes()
        resolver = ResearchSquarePdfResolver()
        async with httpx.AsyncClient() as client:
            cases = [page.replace(b"v1.pdf?", b"v2.pdf?"),
                     page.replace(raw["doi"].encode(), b"10.21203/rs.3.rs-999/v1"),
                     page.replace(b"www.researchsquare.com/article/rs-11017119/v1.pdf", b"evil.example/article/rs-11017119/v1.pdf"),
                     b"<html>Cloudflare verification</html>"]
            for content in cases:
                with self.subTest(content=content[:50]), patch("app.sources.preprint_pdf.request_content", new_callable=AsyncMock, return_value=content):
                    self.assertIsNone(await resolver.resolve(raw, client))

    async def test_timeout_retains_completed_pdfs_and_all_basic_records(self):
        """整批预算耗尽后取消慢请求，保留已补齐的 PDF 和未补齐论文的基础字段。"""
        records = [record("biorxiv"), record("medrxiv")]
        papers = [EuropePmcAdapter.to_paper(row) for row in records]
        cancelled = asyncio.Event()

        async def request(url, **kwargs):
            # bioRxiv 立即完成，medRxiv 持续等待；finally 用来确认等待任务确实被取消。
            if "/details/biorxiv/" in url:
                return fixture("biorxiv-details")
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        enricher = PreprintPdfEnricher()
        enricher.budget_seconds = 0.03
        with patch("app.sources.preprint_pdf.request_json", side_effect=request):
            await enricher.enrich(records, papers)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(len(papers), 2)
        self.assertIsNotNone(papers[0].pdf_url)
        self.assertIsNone(papers[1].pdf_url)
        self.assertEqual(papers[1].doi, records[1]["doi"])

    async def test_origin_errors_keep_local_search_successful(self):
        """原站的 403、429、502 只影响补查，不应让成功的关键词检索整体失败。"""
        for status in (403, 429, 502):
            def client(**kwargs):
                return httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(status)), **kwargs)

            with self.subTest(status=status), \
                 patch("app.sources.europepmc.request_json", new_callable=AsyncMock,
                       return_value={"hitCount": 1, "resultList": {"result": [record("biorxiv")]}}), \
                 patch("app.sources.preprint_pdf.create_http_client", side_effect=client):
                response = TestClient(app).get("/api/papers/search", params={"q": "test", "platform": "biorxiv"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["meta"]["total"], 1)
            self.assertIsNone(response.json()["data"][0]["pdfUrl"])

    async def test_rxiv_rate_limit_stops_queued_bio_and_med_requests(self):
        """两个 Rxiv 共用官方服务，任一站点被限流后都应停止同服务排队中的补查。"""
        records = [record("biorxiv"), record("medrxiv")]
        papers = [EuropePmcAdapter.to_paper(row) for row in records]
        response = httpx.Response(429, request=httpx.Request("GET", "https://api.biorxiv.org/"))
        error = httpx.HTTPStatusError("rate limited", request=response.request, response=response)
        enricher = PreprintPdfEnricher()
        # 将并发设为 1，确保第二个站点排队，以便观察首个 429 是否阻止其发出。
        enricher.concurrency = 1
        with patch("app.sources.preprint_pdf.request_json", new_callable=AsyncMock, side_effect=error) as request:
            await enricher.enrich(records, papers)
        request.assert_awaited_once()
        self.assertTrue(all(paper.pdf_url is None for paper in papers))
