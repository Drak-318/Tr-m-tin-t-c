import unittest
from scanner.collectors import SourceFetchError, _resolve_aggregator_links, _collect_primary
from scanner.collectors import parse_feed, _deduplicate_items, find_next_page, parse_html_items
from bs4 import BeautifulSoup

class CollectorTests(unittest.TestCase):

    def test_rss_feed_supplements_partial_primary_listing(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from scanner.collectors import scan_source

        feed = b"""<rss><channel>
          <item><title>Thong tu 12/2026/TT-BTC ve phi</title>
            <link>https://example.gov.vn/vb/12</link>
            <pubDate>Mon, 16 Nov 2026 10:00:00 GMT</pubDate></item>
        </channel></rss>"""
        response = SimpleNamespace(content=feed, url="https://news.google.com/rss", status_code=200)
        fake_session = SimpleNamespace(close=lambda: None)
        primary = ([{"title":"Nghi dinh 1/2026/ND-CP","link":"https://example.gov.vn/vb/1","published_date":None}], 1, 200)
        with patch("scanner.collectors.make_session", return_value=fake_session), \
             patch("scanner.collectors._collect_primary", return_value=primary), \
             patch("scanner.collectors.fetch_response", return_value=response):
            result = scan_source(
                {"name":"Example","url":"https://example.gov.vn/list"},
                {"max_items":100,"max_pages":3,"fallback_feed_urls":["https://news.google.com/rss"]}
            )
        self.assertEqual(len(result["items"]), 2)
        self.assertTrue(result["feed_supplement_used"])
        self.assertFalse(result["fallback_used"])
        supplement = next(item for item in result["items"] if item["link"].endswith("/12"))
        self.assertIsNone(supplement["published_date"])
        self.assertEqual(supplement["date_source"], "fallback_aggregator")


    def test_failed_review_pages_retry_after_seven_day_cooldown(self):
        from datetime import datetime, timezone, timedelta
        from unittest.mock import patch
        from scanner.persistent_memory import pending_review_documents

        old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        recent = datetime.now(timezone.utc).isoformat()
        queue = {
            "https://example.gov.vn/old-failure": {
                "status":"manual_review","verification_status":"manual_review",
                "attempts":3,"last_checked":old
            },
            "https://example.gov.vn/recent-failure": {
                "status":"manual_review","verification_status":"manual_review",
                "attempts":3,"last_checked":recent
            },
            "https://example.gov.vn/human-review": {
                "status":"manual_review","verification_status":"needs_manual_review",
                "attempts":1,"last_checked":old
            },
        }
        with patch("scanner.persistent_memory.load_review_queue", return_value=queue):
            rows = pending_review_documents(limit=20,max_attempts=3,retry_manual_after_days=7)
        urls = {row["link"] for row in rows}
        self.assertIn("https://example.gov.vn/old-failure", urls)
        self.assertNotIn("https://example.gov.vn/recent-failure", urls)
        self.assertNotIn("https://example.gov.vn/human-review", urls)

    def test_keeps_first_page_items_when_next_page_fails(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        html = """<html><body>
          <a href="/van-ban/1">Nghị định 1/2026/NĐ-CP quy định về thủ tục hành chính</a>
          <a rel="next" href="/van-ban?page=2">Trang tiếp</a>
        </body></html>"""
        first = SimpleNamespace(
            url="https://example.gov.vn/van-ban", status_code=200,
            headers={"Content-Type":"text/html"}, text=html, content=html.encode("utf-8")
        )
        config = {"mode":"html","follow_pagination":True}
        with patch("scanner.collectors.fetch_response",
                   side_effect=SourceFetchError("HTTP","HTTP 503",http_status=503)):
            items, pages, status = _collect_primary(
                SimpleNamespace(), "https://example.gov.vn/van-ban", config, 100, 3,
                initial_response=first
            )
        self.assertEqual(status, 200)
        self.assertEqual(len(items), 1)
        self.assertEqual(pages, 1)
        self.assertTrue(config["_partial_errors"])
        self.assertIn("HTTP 503", config["_partial_errors"][0])

    def test_parse_rss_feed(self):
        xml=b"""<rss><channel><item><title>Thong tu 12/2026/TT-BTC</title><link>https://example.gov.vn/vb/12</link><pubDate>Mon, 16 Nov 2026 10:00:00 GMT</pubDate></item></channel></rss>"""
        items=parse_feed(xml)
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]["link"],"https://example.gov.vn/vb/12")
        self.assertIsNotNone(items[0]["published_date"])

    def test_malformed_xml_is_reported_as_parser_error(self):
        with self.assertRaises(SourceFetchError) as ctx:
            parse_feed(b"<rss><channel><item>")
        self.assertEqual(ctx.exception.kind,"PARSER")

    def test_javascript_pager_is_not_returned_as_url(self):
        soup=BeautifulSoup('<a href="javascript:__doPostBack(\'pager\',\'10\')">Next</a>',"html.parser")
        self.assertIsNone(find_next_page(soup,"https://example.gov.vn/list",{"follow_pagination":True}))

    def test_real_next_page_url_is_preserved(self):
        soup=BeautifulSoup('<a rel="next" href="/list?page=2">Next</a>',"html.parser")
        self.assertEqual(find_next_page(soup,"https://example.gov.vn/list",{}),
                         "https://example.gov.vn/list?page=2")


    def test_generic_table_row_reads_number_and_date_outside_title_link(self):
        html="""<table><tbody><tr>
          <td>Số 123/2026/QĐ-UBND</td>
          <td><a href="/van-ban/123">Ban hành bảng giá đất áp dụng trên địa bàn</a></td>
          <td>16/11/2026</td>
        </tr></tbody></table>"""
        items,_=parse_html_items(html,"https://example.gov.vn/van-ban",{})
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]["doc_type"],"Quyết định")
        self.assertEqual(items[0]["doc_number"],"123/2026/QĐ-UBND")
        self.assertEqual(items[0]["published_date"],"2026-11-16")

    def test_table_document_row_extracts_number_and_issue_date(self):
        html="""<table><tbody><tr>
          <td>123-KL/TW</td><td><a href="/van-ban/123">Kết luận của Bộ Chính trị về công tác</a></td>
          <td>13/11/2026</td><td>13/11/2026</td>
        </tr></tbody></table>"""
        items,_=parse_html_items(html,"https://dangcongsan.vn/van-ban-cua-dang",{
            "item_selector":"table tr","title_selector":"td:nth-child(2) a",
            "link_selector":"td:nth-child(2) a","document_number_selector":"td:nth-child(1)",
            "issue_date_selector":"td:nth-child(3)"
        })
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]["doc_number"],"123-KL/TW")
        self.assertEqual(items[0]["doc_type"],"Kết luận")
        self.assertEqual(items[0]["issue_date"],"13/11/2026")
        self.assertIn("ngày 13/11/2026",items[0]["title"])

    def test_detail_page_labelled_issue_date_has_priority(self):
        from scanner.collectors import extract_detail_date
        html='<html><body><div>Ngày ban hành: 10/11/2026</div><meta property="article:published_time" content="2026-11-16T10:00:00+07:00"></body></html>'
        result=extract_detail_date(html)
        self.assertEqual(result["date"],"2026-11-10")
        self.assertEqual(result["basis"],"issue_date_detail")

    def test_detail_page_meta_date_is_labelled_as_source_posted_date(self):
        from scanner.collectors import extract_detail_date
        html='<html><head><meta property="article:published_time" content="2026-11-16T10:00:00+07:00"></head></html>'
        result=extract_detail_date(html)
        self.assertEqual(result["date"],"2026-11-16")
        self.assertEqual(result["basis"],"source_posted_date_detail")

    def test_arbitrary_old_citation_date_is_not_used_as_issue_date(self):
        from scanner.collectors import extract_detail_date
        html='<html><body>Nghị định 320/2025/NĐ-CP ngày 15/12/2025 được sửa đổi.</body></html>'
        result=extract_detail_date(html)
        self.assertEqual(result["basis"],"unknown")

    def test_google_news_link_is_not_used_as_source_date(self):
        from scanner.collectors import verify_document_detail_date
        result=verify_document_detail_date("https://news.google.com/rss/articles/example")
        self.assertEqual(result["basis"],"fetch_error")
        self.assertIn("không dùng ngày Google News",result["error"])

    def test_deduplicate_preserves_fallback_provenance(self):
        items=[{"title":"Nghi dinh 1/2026/ND-CP","link":"https://example.gov.vn/a",
                "published_date":None,"source_published_date":"2026-11-16","date_source":"fallback_aggregator"}]
        result=_deduplicate_items(items,20)
        self.assertEqual(result[0]["date_source"],"fallback_aggregator")
        self.assertIsNone(result[0]["published_date"])


    def test_discovery_rss_accepts_only_allowlisted_official_domains(self):
        from types import SimpleNamespace

        class FakeSession:
            def get(self, url, **kwargs):
                host = "chinhphu.vn" if "official" in url else "example.com"
                return SimpleNamespace(url=f"https://{host}/van-ban/1", ok=True)

        items = [
            {"title":"Nghị định 1/2026/NĐ-CP","link":"https://news.google.com/rss/articles/official"},
            {"title":"Nghị định 2/2026/NĐ-CP","link":"https://news.google.com/rss/articles/untrusted"},
        ]
        result = _resolve_aggregator_links(
            FakeSession(), items, {"allowed_final_domains":["chinhphu.vn"]}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["link"], "https://chinhphu.vn/van-ban/1")


    def test_configured_listing_url_is_used_for_homepage_source(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from scanner.collectors import scan_source

        source = {"name": "Sở Xây dựng Quảng Ngãi", "url": "https://sxd.quangngai.gov.vn/"}
        listing_url = "https://sxd.quangngai.gov.vn/chi-dao-dieu-hanh/van-ban-so-xay-dung"
        seen = {}

        def fake_collect(session, url, config, max_items, max_pages, **kwargs):
            seen["url"] = url
            return ([{"title": "Công văn 1/SXD-VP về việc triển khai", "link": listing_url + "/1"}], 1, 200)

        fake_session = SimpleNamespace(close=lambda: None)
        with patch("scanner.collectors.make_session", return_value=fake_session), patch("scanner.collectors._collect_primary", side_effect=fake_collect):
            result = scan_source(source, {"listing_url": listing_url, "max_items": 20, "max_pages": 1})

        self.assertEqual(seen["url"], listing_url)
        self.assertEqual(len(result["items"]), 1)

    def test_syt_lam_dong_table_selectors_extract_number_and_issue_date(self):
        html = """<table><tbody><tr>
          <td>9901/SYT-TCCB</td><td>25/11/2026</td>
          <td><a href="/van-ban/9901">Báo cáo tình hình thực hiện nhiệm vụ</a></td>
          <td><a href="/files/9901.pdf">Tải về</a></td>
        </tr></tbody></table>"""
        items, _ = parse_html_items(html, "https://syt.lamdong.gov.vn/van-ban-quan-ly", {
            "item_selector": "table tr",
            "title_selector": "td:nth-child(3) a[href]",
            "link_selector": "td:nth-child(3) a[href]",
            "document_number_selector": "td:nth-child(1)",
            "issue_date_selector": "td:nth-child(2)",
        })
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["doc_number"], "9901/SYT-TCCB")
        self.assertEqual(items[0]["published_date"], "25/11/2026")
        self.assertEqual(items[0]["doc_type"], "Công văn")

    def test_sxd_quang_ngai_table_selectors_extract_number_and_issue_date(self):
        html = """<table><tbody><tr>
          <td>1</td><td>9731/SXD-VP</td><td>27/11/2026</td>
          <td><a href="/van-ban/9731">V/v báo cáo thực hiện nhiệm vụ công tác</a></td>
          <td></td><td>Công văn</td><td></td>
        </tr></tbody></table>"""
        items, _ = parse_html_items(html, "https://sxd.quangngai.gov.vn/chi-dao-dieu-hanh/van-ban-so-xay-dung", {
            "item_selector": "table tr",
            "title_selector": "td:nth-child(4) a[href]",
            "link_selector": "td:nth-child(4) a[href]",
            "document_number_selector": "td:nth-child(2)",
            "issue_date_selector": "td:nth-child(3)",
            "document_type_selector": "td:nth-child(6)",
        })
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["doc_number"], "9731/SXD-VP")
        self.assertEqual(items[0]["published_date"], "27/11/2026")
        self.assertEqual(items[0]["doc_type"], "Công văn")

if __name__=="__main__": unittest.main()
