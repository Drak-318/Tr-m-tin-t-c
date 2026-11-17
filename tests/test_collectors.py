import unittest
from scanner.collectors import SourceFetchError
from scanner.collectors import parse_feed, _deduplicate_items, find_next_page
from bs4 import BeautifulSoup

class CollectorTests(unittest.TestCase):
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

    def test_deduplicate_preserves_fallback_provenance(self):
        items=[{"title":"Nghi dinh 1/2026/ND-CP","link":"https://example.gov.vn/a",
                "published_date":None,"source_published_date":"2026-11-16","date_source":"fallback_aggregator"}]
        result=_deduplicate_items(items,20)
        self.assertEqual(result[0]["date_source"],"fallback_aggregator")
        self.assertIsNone(result[0]["published_date"])

if __name__=="__main__": unittest.main()
