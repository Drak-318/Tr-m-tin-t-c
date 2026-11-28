import unittest
from unittest.mock import Mock, patch
import requests

from scanner import sheets


class SheetsRetryTests(unittest.TestCase):
    @patch("scanner.sheets.time.sleep")
    @patch("scanner.sheets.requests.post")
    def test_retries_transient_server_error_then_succeeds(self, post, sleep):
        failed = Mock()
        failed.status_code = 503
        failed.text = "temporary unavailable"
        failed.raise_for_status.side_effect = requests.HTTPError("503", response=failed)
        success = Mock()
        success.raise_for_status.return_value = None
        success.json.return_value = {"status": "ok"}
        post.side_effect = [failed, success]
        with patch("scanner.sheets.WEB_APP_URL", "https://script.example/exec"):
            result = sheets._post({"action": "get_sources"}, attempts=2)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(5)

    @patch("scanner.sheets.time.sleep")
    @patch("scanner.sheets.requests.post")
    def test_does_not_retry_permanent_client_error(self, post, sleep):
        failed = Mock()
        failed.status_code = 400
        failed.text = "bad request"
        failed.raise_for_status.side_effect = requests.HTTPError("400", response=failed)
        post.return_value = failed
        with patch("scanner.sheets.WEB_APP_URL", "https://script.example/exec"):
            with self.assertRaisesRegex(RuntimeError, "HTTP 400"):
                sheets._post({"action": "get_sources"}, attempts=3)
        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
