import unittest
from unittest.mock import Mock, patch
import requests

from scanner.collectors import scan_source

class AppsScriptFallbackTests(unittest.TestCase):
    @patch("scanner.collectors.make_session")
    def test_uses_apps_script_after_primary_ssl_failure(self, make_session):
        session = Mock()
        session.get.side_effect = requests.exceptions.SSLError("certificate verify failed")
        make_session.return_value = session
        html = '<html><body><a href="/van-ban/1">Nghị định số 123/2026/NĐ-CP về hướng dẫn</a></body></html>'
        fetcher = Mock(return_value={"status":"ok","http_status":200,"content_type":"text/html","body":html})
        result = scan_source({"url":"https://example.gov.vn/van-ban","name":"Nguồn thử"},
                             {"mode":"auto","max_pages":1,"max_items":20},fetcher)
        self.assertEqual(result["retrieval_method"],"apps_script")
        self.assertTrue(result["fallback_used"])
        self.assertEqual(len(result["items"]),1)
        self.assertEqual(result["items"][0]["retrieval_method"],"apps_script")
        fetcher.assert_called_once()

    @patch("scanner.collectors.make_session")
    def test_does_not_call_apps_script_when_primary_is_accessible_but_empty(self, make_session):
        response = Mock()
        response.status_code = 200
        response.url = "https://example.gov.vn/van-ban"
        response.headers = {"Content-Type":"text/html"}
        response.text = "<html><body><p>Trang đang cập nhật</p></body></html>"
        response.content = response.text.encode()
        session = Mock()
        session.get.return_value = response
        make_session.return_value = session
        fetcher = Mock()
        result = scan_source({"url":response.url,"name":"Nguồn thử"},
                             {"mode":"auto","max_pages":1,"max_items":20},fetcher)
        self.assertEqual(result["status"],"Đã truy cập, chưa tìm thấy mục")
        fetcher.assert_not_called()

if __name__ == "__main__": unittest.main()
