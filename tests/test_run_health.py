import unittest

from scanner.run_health import validate_run_outcome


class RunHealthTests(unittest.TestCase):
    def test_all_sources_failed_is_not_success(self):
        errors = validate_run_outcome(5, 5, 0, True)
        self.assertTrue(any("Tất cả 5 nguồn" in item for item in errors))

    def test_partial_source_failure_is_reported_but_not_blocking(self):
        self.assertEqual(validate_run_outcome(5, 2, 0, True), [])

    def test_pending_sheets_export_blocks_success(self):
        errors = validate_run_outcome(5, 0, 2, True)
        self.assertTrue(any("2 gói dữ liệu chưa được Google Sheets xác nhận" in item for item in errors))

    def test_missing_apps_script_url_blocks_pending_export(self):
        errors = validate_run_outcome(5, 0, 1, False)
        self.assertTrue(any("chưa cấu hình Apps Script URL" in item for item in errors))

    def test_empty_scan_is_not_success(self):
        errors = validate_run_outcome(0, 0, 0, True)
        self.assertTrue(any("Không có nguồn nào" in item for item in errors))

    def test_clean_run_passes(self):
        self.assertEqual(validate_run_outcome(10, 1, 0, True), [])


if __name__ == "__main__":
    unittest.main()
