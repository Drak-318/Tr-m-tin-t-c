import unittest
from datetime import datetime
from scanner.normalizer import (
    canonicalize_url, extract_doc_info, classify_and_score,
    classify_document, document_identity, is_too_old, make_fingerprint, has_document_date,
)

class NormalizerTests(unittest.TestCase):

    def test_infer_type_from_number_suffix_when_title_omits_type(self):
        cases = [
            ("Số 123/2026/NĐ-CP về chính sách thuế", "Nghị định", "123/2026/NĐ-CP"),
            ("Số 45/2026/TT-BTC về phí và lệ phí", "Thông tư", "45/2026/TT-BTC"),
            ("Số 18/2026/QĐ-UBND ban hành bảng giá đất", "Quyết định", "18/2026/QĐ-UBND"),
            ("Số 12/2026/NQ-HĐND về mức học phí", "Nghị quyết", "12/2026/NQ-HĐND"),
            ("Số 123-KL/TW về công tác xây dựng Đảng", "Kết luận", "123-KL/TW"),
        ]
        for title, expected_type, expected_number in cases:
            with self.subTest(title=title):
                self.assertEqual(extract_doc_info(title), (expected_type, expected_number))

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

    def test_fallback_document_number_pattern_is_valid(self):
        self.assertEqual(extract_doc_info("Kế hoạch triển khai thực hiện số 606/KH-UBND trên địa bàn"),
                         ("Kế hoạch","606/KH-UBND"))

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


    def test_local_land_compensation_policy_is_kept(self):
        keep, score = classify_and_score(
            "Quyết định 12/2026/QĐ-UBND ban hành chính sách bồi thường, hỗ trợ khi thu hồi đất",
            "UBND tỉnh An Giang", "Quyết định", "12/2026/QĐ-UBND", "Văn Bản TW"
        )
        self.assertTrue(keep)
        self.assertEqual(score, 30)

    def test_local_land_price_table_is_kept(self):
        keep, _ = classify_and_score(
            "Quyết định ban hành bảng giá đất trên địa bàn tỉnh",
            "UBND tỉnh Đồng Nai", "Quyết định", "", "Địa phương"
        )
        self.assertTrue(keep)

    def test_local_personal_land_recovery_is_excluded(self):
        keep, _ = classify_and_score(
            "Quyết định thu hồi đất của hộ ông Nguyễn Văn A để thực hiện dự án",
            "UBND tỉnh An Giang", "Quyết định", "12/QĐ-UBND", "Địa phương"
        )
        self.assertFalse(keep)

    def test_local_individual_award_is_excluded(self):
        keep, _ = classify_and_score(
            "Quyết định về việc khen thưởng cho các cá nhân có thành tích",
            "UBND tỉnh An Giang", "Quyết định", "", "Địa phương"
        )
        self.assertFalse(keep)

    def test_local_individual_fine_is_excluded(self):
        keep, _ = classify_and_score(
            "Quyết định xử phạt vi phạm hành chính đối với Công ty ABC",
            "UBND tỉnh An Giang", "Quyết định", "", "Địa phương"
        )
        self.assertFalse(keep)

    def test_local_individual_certificate_is_excluded(self):
        keep, _ = classify_and_score(
            "Quyết định cấp chứng chỉ hành nghề cho ông Nguyễn Văn A",
            "Sở Y tế tỉnh An Giang", "Quyết định", "", "Địa phương"
        )
        self.assertFalse(keep)

    def test_local_unrelated_administrative_decision_is_excluded(self):
        keep, _ = classify_and_score(
            "Quyết định phê duyệt kết quả tuyển chọn một cá nhân",
            "UBND tỉnh An Giang", "Quyết định", "", "Địa phương"
        )
        self.assertFalse(keep)

    def test_mislabelled_local_source_is_still_filtered(self):
        keep, _ = classify_and_score(
            "Quyết định khen thưởng tập thể",
            "Sở Nội vụ Gia Lai", "Quyết định", "", "Văn Bản TW"
        )
        self.assertFalse(keep)


    def test_central_general_reward_policy_is_not_excluded(self):
        keep, _ = classify_and_score(
            "Nghị định quy định chính sách thi đua, khen thưởng đối với cán bộ, công chức",
            "Chính phủ", "Nghị định", "99/2026/NĐ-CP", "Văn Bản TW"
        )
        self.assertTrue(keep)

    def test_central_rule_on_administrative_penalties_is_kept(self):
        keep, _ = classify_and_score(
            "Nghị định quy định xử phạt vi phạm hành chính trong lĩnh vực thuế",
            "Chính phủ", "Nghị định", "99/2026/NĐ-CP", "Văn Bản TW"
        )
        self.assertTrue(keep)

    def test_local_health_and_education_policy_are_kept(self):
        health = classify_and_score("Quyết định về chính sách hỗ trợ viện phí", "UBND tỉnh", "Quyết định", "", "Địa phương")[0]
        education = classify_and_score("Nghị quyết về mức học phí năm học mới", "HĐND tỉnh", "Nghị quyết", "", "Địa phương")[0]
        self.assertTrue(health)
        self.assertTrue(education)


    def test_central_instrument_found_on_local_portal_is_kept(self):
        keep, score = classify_and_score(
            "Nghị định 23/2026/NĐ-CP quy định về chính sách thuế",
            "Đoàn ĐBQH và HĐND tỉnh Ninh Bình", "Nghị định", "23/2026/NĐ-CP", "Địa phương"
        )
        self.assertTrue(keep)
        self.assertNotEqual(score, 30)

    def test_local_individual_land_certificate_is_excluded(self):
        keep, _ = classify_and_score(
            "Quyết định cấp giấy chứng nhận quyền sử dụng đất cho ông Nguyễn Văn A",
            "UBND tỉnh An Giang", "Quyết định", "", "Địa phương"
        )
        self.assertFalse(keep)

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


    def test_official_letter_number_without_type_prefix_is_recognized(self):
        self.assertEqual(extract_doc_info("11560/VPCP-CN 11/11/2026"),
                         ("Công văn", "11560/VPCP-CN"))

    def test_date_like_fragment_is_not_used_as_document_identity(self):
        a=document_identity("11/2026","11560/VPCP-CN 11/11/2026","Văn phòng Chính phủ","https://a.gov.vn/doc/1")
        b=document_identity("11/2026","11627/VPCP-CN 12/11/2026","Văn phòng Chính phủ","https://a.gov.vn/doc/2")
        self.assertNotEqual(a,b)

    def test_same_local_number_from_different_agencies_is_not_merged(self):
        a=document_identity("12/2026/QĐ-UBND","Quyết định 12/2026/QĐ-UBND","UBND tỉnh An Giang","https://a.gov.vn/doc")
        b=document_identity("12/2026/QĐ-UBND","Quyết định 12/2026/QĐ-UBND","UBND tỉnh Đồng Nai","https://b.gov.vn/doc")
        self.assertNotEqual(a,b)


    def test_government_resolution_is_classified_as_legal_normative_document(self):
        self.assertEqual(
            classify_document(
                "Nghị quyết 01/2026/NQ-CP về nhiệm vụ, giải pháp",
                "Chính phủ", "Nghị quyết", "01/2026/NQ-CP"
            ),
            "Văn bản quy phạm pháp luật"
        )

    def test_local_hdn_d_resolution_is_classified_as_legal_normative_document(self):
        title = "Nghị quyết 12/2026/NQ-HĐND quy định mức học phí"
        self.assertEqual(
            classify_document(title, "HĐND tỉnh An Giang", "Nghị quyết", "12/2026/NQ-HĐND"),
            "Văn bản quy phạm pháp luật"
        )
        keep, _ = classify_and_score(
            title, "HĐND tỉnh An Giang", "Nghị quyết", "12/2026/NQ-HĐND", "Địa phương"
        )
        self.assertTrue(keep)

    def test_party_resolution_remains_party_document(self):
        self.assertEqual(
            classify_document("Nghị quyết 18-NQ/TW về công tác xây dựng Đảng",
                              "Ban Chấp hành Trung ương", "Nghị quyết", "18-NQ/TW"),
            "Văn bản Đảng"
        )



    def test_local_rollout_dispatch_citing_central_decree_is_excluded(self):
        title = "Công văn số 123/SNV-VP về việc triển khai Nghị định 45/2026/NĐ-CP về chính sách hỗ trợ người dân trong lĩnh vực đất đai"
        doc_type, number = extract_doc_info(title)
        self.assertEqual((doc_type, number), ("Công văn", "123/SNV-VP"))
        keep, _ = classify_and_score(
            title, "Sở Nội vụ Lâm Đồng", doc_type, number, "Địa phương"
        )
        self.assertFalse(keep)

    def test_local_hot_topic_dispatch_without_central_rollout_can_be_kept(self):
        title = "Công văn về việc rà soát, tháo gỡ khó khăn trong cấp giấy chứng nhận quyền sử dụng đất"
        keep, _ = classify_and_score(
            title, "Sở Tài nguyên và Môi trường Lâm Đồng", "Công văn", "", "Địa phương"
        )
        self.assertTrue(keep)

    def test_local_direct_central_decree_is_kept_as_original_instrument(self):
        title = "Nghị định 45/2026/NĐ-CP quy định về chính sách đất đai"
        keep, score = classify_and_score(
            title, "Sở Tư pháp Lâm Đồng", "Nghị định", "45/2026/NĐ-CP", "Địa phương"
        )
        self.assertTrue(keep)
        self.assertEqual(score, 10)

    def test_local_cited_decree_without_original_document_title_is_not_promoted(self):
        title = "Công văn hướng dẫn triển khai Nghị định 45/2026/NĐ-CP về chính sách đất đai"
        keep, _ = classify_and_score(
            title, "Sở Nội vụ Lâm Đồng", "Công văn", "", "Địa phương"
        )
        self.assertFalse(keep)

    def test_local_individual_company_permit_amendment_is_excluded(self):
        title = "Quyết định điều chỉnh giấy phép hoạt động cho Công ty ABC"
        keep, _ = classify_and_score(
            title, "Sở Y tế Lâm Đồng", "Quyết định", "123/QĐ-SYT", "Địa phương"
        )
        self.assertFalse(keep)

    def test_local_individual_permit_revocation_is_excluded(self):
        title = "Quyết định thu hồi giấy phép hoạt động đối với Doanh nghiệp ABC"
        keep, _ = classify_and_score(
            title, "Sở Xây dựng Lâm Đồng", "Quyết định", "123/QĐ-SXD", "Địa phương"
        )
        self.assertFalse(keep)

    def test_local_resolution_on_broad_education_policy_is_kept(self):
        title = "Nghị quyết quy định mức học phí đối với cơ sở giáo dục công lập"
        keep, _ = classify_and_score(
            title, "HĐND tỉnh Lâm Đồng", "Nghị quyết", "12/2026/NQ-HĐND", "Địa phương"
        )
        self.assertTrue(keep)



    def test_local_dispatch_without_own_number_is_not_misread_as_cited_decree(self):
        title = "Công văn hướng dẫn triển khai Nghị định 45/2026/NĐ-CP về đất đai"
        self.assertEqual(extract_doc_info(title), ("Công văn", "Đang cập nhật"))
        keep, _ = classify_and_score(
            title, "Sở Tư pháp Lâm Đồng", "Công văn", "Đang cập nhật", "Địa phương"
        )
        self.assertFalse(keep)



    def test_local_announcement_rolling_out_central_decree_is_excluded(self):
        title = "Thông báo triển khai Nghị định 45/2026/NĐ-CP về chính sách đất đai"
        keep, _ = classify_and_score(
            title, "Sở Nội vụ Lâm Đồng", "Thông báo", "Đang cập nhật", "Địa phương"
        )
        self.assertFalse(keep)

    def test_central_national_assembly_resolution_is_recognized_on_local_portal(self):
        title = "Nghị quyết 12/2026/NQ-QH16 về chính sách giáo dục"
        keep, score = classify_and_score(
            title, "Sở Giáo dục và Đào tạo Lâm Đồng", "Nghị quyết",
            "12/2026/NQ-QH16", "Địa phương"
        )
        self.assertTrue(keep)
        self.assertEqual(score, 10)

    def test_local_company_certificate_case_is_excluded(self):
        title = "Quyết định cấp giấy chứng nhận quyền sử dụng đất cho Công ty ABC"
        keep, _ = classify_and_score(
            title, "UBND tỉnh Lâm Đồng", "Quyết định", "123/QĐ-UBND", "Địa phương"
        )
        self.assertFalse(keep)


if __name__=="__main__": unittest.main()
