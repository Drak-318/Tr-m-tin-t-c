import unittest
from datetime import datetime
from scanner.normalizer import (
    canonicalize_url, extract_doc_info, classify_and_score,
    classify_document, document_identity, is_too_old,
)

class NormalizerTests(unittest.TestCase):
    def test_extract_common_document_numbers(self):
        cases=[
            ("Nghị định 413/2026/NĐ-CP quy định về...","Nghị định","413/2026/NĐ-CP"),
            ("Nghị quyết 18-NQ/TW về một số vấn đề...","Nghị quyết","18-NQ/TW"),
            ("Quyết định 3538/QĐ-BYT về việc...","Quyết định","3538/QĐ-BYT"),
            ("Văn bản hợp nhất 113/2026/VBHN-TT-BNNMT","Văn bản hợp nhất","113/2026/VBHN-TT-BNNMT"),
            ("Công văn 1234/VPCP-KTTH về việc triển khai...","Công văn","1234/VPCP-KTTH"),
        ]
        for title,typ,num in cases:
            with self.subTest(title=title):
                self.assertEqual(extract_doc_info(title),(typ,num))

    def test_reject_menu_links(self): self.assertEqual(extract_doc_info("Trang chủ"),(None,None))

    def test_canonical_url_removes_tracking(self):
        self.assertEqual(canonicalize_url("HTTPS://Example.com/path/?utm_source=x&fbclid=abc#top"),"https://example.com/path/")

    def test_central_document_is_kept(self):
        keep,score=classify_and_score("Nghị định 413/2026/NĐ-CP quy định...","Nguồn Chính phủ","Nghị định","413/2026/NĐ-CP","Văn Bản TW")
        self.assertTrue(keep); self.assertLess(score,20)

    def test_draft_separate(self):
        self.assertEqual(classify_document("Dự thảo Nghị định quy định về...","Cổng Bộ","Nghị định","", "https://example.gov.vn"),"Dự thảo")

    def test_party_document_recognized(self):
        self.assertEqual(classify_document("Nghị quyết 18-NQ/TW về ...","Nguồn","Nghị quyết","18-NQ/TW"),"Văn bản Đảng")

    def test_official_letter_has_own_category(self):
        self.assertEqual(classify_document("Công văn 1234/VPCP-KTTH về triển khai","Văn phòng Chính phủ","Công văn","1234/VPCP-KTTH"),"Công văn")

    def test_old_issue_date_wins_over_recent_repost_date(self):
        self.assertTrue(is_too_old("Quyết định ban hành ngày 01/01/2024", "12/QĐ-UBND", 60, "2026-11-17", now=datetime(2026,11,17)))

    def test_recent_publication_date_used_when_issue_date_unknown(self):
        self.assertFalse(is_too_old("Công văn 1234/VPCP-KTTH về việc triển khai","1234/VPCP-KTTH",60,"2026-11-10",now=datetime(2026,11,17)))

    def test_same_number_different_issuer_not_same_key(self):
        a=document_identity("12/2026/QĐ-UBND","Quyết định 12/2026/QĐ-UBND","", "https://a.vn")
        b=document_identity("12/2026/QĐ-STC","Quyết định 12/2026/QĐ-STC","", "https://b.vn")
        self.assertNotEqual(a,b)

if __name__=="__main__": unittest.main()
