import unittest
from unittest.mock import Mock, patch
import requests
from pathlib import Path

from scanner.collectors import scan_source


class GitHubOnlyCollectionTests(unittest.TestCase):
    @patch("scanner.collectors.make_session")
    def test_ssl_failure_is_recorded_without_apps_script_proxy(self, make_session):
        session = Mock()
        session.get.side_effect = requests.exceptions.SSLError("certificate verify failed")
        make_session.return_value = session
        result = scan_source(
            {"url": "https://example.gov.vn/van-ban", "name": "Nguồn thử"},
            {"mode": "auto", "max_pages": 1, "max_items": 20},
        )
        self.assertTrue(result["status"].startswith("Lỗi: SSL"))
        self.assertIn("certificate verify failed", result["error"])
        self.assertNotIn("apps_script", result.get("retrieval_method", ""))

    @patch("scanner.collectors.make_session")
    def test_accessible_empty_page_is_not_misreported_as_network_failure(self, make_session):
        response = Mock()
        response.status_code = 200
        response.url = "https://example.gov.vn/van-ban"
        response.headers = {"Content-Type": "text/html"}
        response.text = "<html><body><p>Trang đang cập nhật</p></body></html>"
        response.content = response.text.encode()
        session = Mock()
        session.get.return_value = response
        make_session.return_value = session
        result = scan_source(
            {"url": response.url, "name": "Nguồn thử"},
            {"mode": "auto", "max_pages": 1, "max_items": 20},
        )
        self.assertEqual(result["status"], "Đã truy cập, chưa tìm thấy mục")

    def test_apps_script_is_not_a_source_fetch_proxy_or_source_registry(self):
        code = Path("apps_script/Code.gs").read_text(encoding="utf-8")
        self.assertNotIn("fetchSource_", code)
        self.assertNotIn('data.action === "fetch_source"', code)
        self.assertNotIn('data.action === "get_sources"', code)
        self.assertNotIn("UrlFetchApp.fetch", code)
        self.assertIn('version: "15.0"', code)


if __name__ == "__main__":
    unittest.main()
