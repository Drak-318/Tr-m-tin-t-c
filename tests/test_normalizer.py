import unittest

from scanner.normalizer import (
    canonicalize_url,
    extract_doc_info,
    classify_and_score,
)

class NormalizerTests(unittest.TestCase):
    def test_extract_common_document_numbers(self):
        cases = [
            ("Nghị định 413/2026/NĐ-CP quy định về...", "Nghị định", "413/2026/NĐ-CP"),
            ("Nghị quyết 18-NQ/TW về một số vấn đề...", "Nghị quyết", "18-NQ/TW"),
            ("Quyết định 3538/QĐ-BYT về việc...", "Quyết định", "3538/QĐ-BYT"),
            ("Văn bản hợp nhất 113/2026/VBHN-TT-BNNMT", "Văn bản hợp nhất", "113/2026/VBHN-TT-BNNMT"),
        ]
        for title, expected_type, expected_number in cases:
            with self.subTest(title=title):
                doc_type, doc_number = extract_doc_info(title)
                self.assertEqual(doc_type, expected_type)
                self.assertEqual(doc_number, expected_number)

    def test_reject_menu_links(self):
        self.assertEqual(extract_doc_info("Trang chủ"), (None, None))

    def test_canonical_url_removes_tracking(self):
        self.assertEqual(
            canonicalize_url("HTTPS://Example.com/path/?utm_source=x&fbclid=abc#top"),
            "https://example.com/path/",
        )

    def test_central_document_is_kept(self):
        keep, score = classify_and_score(
            "Nghị định 413/2026/NĐ-CP quy định...", "Nguồn Chính phủ",
            "Nghị định", "413/2026/NĐ-CP", "Văn Bản TW",
        )
        self.assertTrue(keep)
        self.assertLess(score, 20)

if __name__ == "__main__":
    unittest.main()
