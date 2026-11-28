import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scanner import source_discovery as discovery


class SourceDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "discovered_sources.json"
        self.patch = patch.object(discovery, "DISCOVERY_PATH", self.path)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_extracts_same_site_listing_link_only(self):
        html = """
        <a href="/van-ban-phap-luat">Văn bản pháp luật</a>
        <a href="https://other.gov.vn/van-ban">Văn bản ngoài</a>
        <a href="/van-ban/123">Thông tư số 12/2026/TT-BTC về phí</a>
        <a href="/news/latest">Tin mới</a>
        """
        rows = discovery.extract_source_candidates(
            html, "https://example.gov.vn/", "Cổng thông tin", "Văn Bản TW"
        )
        self.assertEqual(len(rows), 2)
        by_url = {row["url"]: row for row in rows}
        self.assertIn("https://example.gov.vn/van-ban-phap-luat", by_url)
        self.assertIn("https://other.gov.vn/van-ban", by_url)
        self.assertEqual(by_url["https://example.gov.vn/van-ban-phap-luat"]["status"], "pending")
        self.assertEqual(by_url["https://other.gov.vn/van-ban"]["group"], "Địa phương")


    def test_discovers_cross_agency_official_portal_as_hub_not_active_source(self):
        html = '<a href="https://snv.lamdong.gov.vn/">Sở Nội vụ tỉnh Lâm Đồng</a>'
        rows = discovery.extract_source_candidates(
            html, "https://moha.gov.vn/", "Cơ quan Trung ương", "Văn Bản TW"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], "https://snv.lamdong.gov.vn")
        self.assertEqual(rows[0]["group"], "Địa phương")
        self.assertEqual(rows[0]["candidate_kind"], "portal_hub")
        discovery.record_candidates(rows, path=self.path)
        self.assertEqual(discovery.active_sources(path=self.path), [])
        self.assertEqual(len(discovery.pending_candidates(path=self.path)), 1)

    def test_discovers_central_ministry_from_local_portal_directory(self):
        html = '<a href="https://moha.gov.vn/">Bộ Nội vụ</a>'
        rows = discovery.extract_source_candidates(
            html, "https://snv.lamdong.gov.vn/", "Sở Nội vụ Lâm Đồng", "Địa phương"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["group"], "Văn Bản TW")
        self.assertEqual(rows[0]["candidate_kind"], "portal_hub")

    def test_ignores_cross_site_non_official_or_unlabelled_links(self):
        html = '''
        <a href="https://example.com/van-ban">Văn bản</a>
        <a href="https://random.gov.vn/">Trang chủ</a>
        <a href="https://facebook.com/example">Sở Nội vụ</a>
        '''
        rows = discovery.extract_source_candidates(
            html, "https://moha.gov.vn/", "Bộ", "Văn Bản TW"
        )
        self.assertEqual(rows, [])

    def test_candidate_becomes_active_only_after_explicit_validation_update(self):
        rows = discovery.extract_source_candidates(
            '<a href="/van-ban">Văn bản</a>',
            "https://example.gov.vn/", "Cổng", "Văn Bản TW"
        )
        discovery.record_candidates(rows, path=self.path)
        self.assertEqual(len(discovery.pending_candidates(path=self.path)), 1)
        self.assertEqual(discovery.active_sources(path=self.path), [])
        url = rows[0]["url"]
        discovery.update_candidate(url, {"status": "active", "validated_document_count": 3}, path=self.path)
        self.assertEqual(discovery.pending_candidates(path=self.path), [])
        self.assertEqual(discovery.active_sources(path=self.path)[0]["url"], url)

    def test_repeated_candidate_is_not_duplicated(self):
        rows = discovery.extract_source_candidates(
            '<a href="/van-ban">Văn bản</a>',
            "https://example.gov.vn/", "Cổng", "Văn Bản TW"
        )
        self.assertEqual(discovery.record_candidates(rows, path=self.path), 1)
        self.assertEqual(discovery.record_candidates(rows, path=self.path), 0)
        self.assertEqual(len(discovery.pending_candidates(path=self.path)), 1)


if __name__ == "__main__":
    unittest.main()
