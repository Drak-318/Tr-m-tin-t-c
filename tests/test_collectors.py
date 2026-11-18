import unittest
from scanner.collectors import SourceFetchError, _resolve_aggregator_links
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

if __name__=="__main__": unittest.main()
