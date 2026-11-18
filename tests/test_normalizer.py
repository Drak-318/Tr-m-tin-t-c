import unittest
from datetime import datetime
from scanner.normalizer import (
    canonicalize_url, extract_doc_info, classify_and_score,
    classify_document, document_identity, is_too_old, make_fingerprint, has_document_date,
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

    def test_phrase_phap_luat_is_not_misclassified_as_luat(self):
        title="Văn bản số 10582/SGDĐT-VP V/v hưởng ứng Cuộc thi trực tuyến tìm hiểu pháp luật"
        self.assertNotEqual(extract_doc_info(title)[0],"Luật")

    def test_luat_at_title_start_is_still_recognized(self):
        self.assertEqual(extract_doc_info("Luật số 12/2026/QH16 về ..."),
                         ("Luật","12/2026/QH16"))

    def test_official_letter_number_with_vv_is_classified_as_cong_van(self):
        title="Văn bản số 10582/SGDĐT-VP V/v hưởng ứng Cuộc thi trực tuyến tìm hiểu pháp luật"
        self.assertEqual(extract_doc_info(title),("Công văn","10582/SGDĐT-VP"))

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

    def test_missing_date_is_not_treated_as_verified_recent(self):
        self.assertFalse(has_document_date("Công văn 1234/VPCP-KTTH về việc triển khai",None))

    def test_title_issue_date_is_a_reliable_date(self):
        self.assertTrue(has_document_date("Quyết định ban hành ngày 10/11/2026",None))

    def test_recent_publication_date_used_when_issue_date_unknown(self):
        self.assertFalse(is_too_old("Công văn 1234/VPCP-KTTH về việc triển khai","1234/VPCP-KTTH",60,"2026-11-10",now=datetime(2026,11,17)))

    def test_recent_source_date_keeps_old_number_year(self):
        self.assertFalse(is_too_old("Nghị định 320/2025/NĐ-CP", "320/2025/NĐ-CP", 60,
                                    "2026-11-17", now=datetime(2026,11,17)))

    def test_undated_old_number_is_kept_for_manual_review(self):
        self.assertFalse(is_too_old("Nghị định 320/2025/NĐ-CP", "320/2025/NĐ-CP", 60,
                                    None, now=datetime(2026,11,17)))

    def test_document_with_known_old_issue_date_is_excluded(self):
        self.assertTrue(is_too_old("Nghị định ban hành ngày 01/01/2025", "320/2025/NĐ-CP", 60,
                                   "2026-11-17", now=datetime(2026,11,17)))

    def test_current_year_draft_amending_old_instrument_is_retained(self):
        self.assertFalse(is_too_old("Dự thảo Nghị định sửa đổi Nghị định 320/2025/NĐ-CP",
                                    "320/2025/NĐ-CP", 60, None, now=datetime(2026,11,17)))

    def test_current_year_amendment_of_old_instrument_is_retained(self):
        self.assertFalse(is_too_old("Nghị định 141/2026/NĐ-CP sửa đổi Nghị định 320/2025/NĐ-CP",
                                    "141/2026/NĐ-CP", 60, "2026-11-10", now=datetime(2026,11,17)))

    def test_source_date_is_labelled_as_fallback(self):
        from scanner.normalizer import resolve_document_date
        date, basis = resolve_document_date("Công văn 1234/VPCP-KTTH", "2026-11-10")
        self.assertEqual(date.strftime("%Y-%m-%d"), "2026-11-10")
        self.assertEqual(basis, "source_posted_date")

    def test_unknown_date_has_no_fabricated_date(self):
        from scanner.normalizer import resolve_document_date
        date, basis = resolve_document_date("Công văn 1234/VPCP-KTTH", None)
        self.assertIsNone(date)
        self.assertEqual(basis, "unknown")

    def test_fingerprint_is_stable(self):
        self.assertEqual(make_fingerprint("12/2026/QĐ-UBND","Quyết định 12/2026/QĐ-UBND"),make_fingerprint("12/2026/QĐ-UBND","Quyết định 12/2026/QĐ-UBND"))

    def test_same_number_different_issuer_not_same_key(self):
        a=document_identity("12/2026/QĐ-UBND","Quyết định 12/2026/QĐ-UBND","", "https://a.vn")
        b=document_identity("12/2026/QĐ-STC","Quyết định 12/2026/QĐ-STC","", "https://b.vn")
        self.assertNotEqual(a,b)

    def test_same_local_number_different_provinces_not_same_key(self):
        a=document_identity("12/2026/QĐ-UBND","Quyết định 12/2026/QĐ-UBND của UBND tỉnh An Giang","", "https://a.vn")
        b=document_identity("12/2026/QĐ-UBND","Quyết định 12/2026/QĐ-UBND của UBND tỉnh Đồng Nai","", "https://b.vn")
        self.assertNotEqual(a,b)

    def test_local_number_without_locality_keeps_different_sources_separate(self):
        a=document_identity("12/2026/QĐ-UBND","Quyết định 12/2026/QĐ-UBND","UBND","https://a.vn")
        b=document_identity("12/2026/QĐ-UBND","Quyết định 12/2026/QĐ-UBND","UBND","https://b.vn")
        self.assertNotEqual(a,b)

if __name__=="__main__": unittest.main()
