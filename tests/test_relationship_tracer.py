import unittest
from scanner.relationship_tracer import extract_document_references, merge_relationships, resolve_reference_candidates, _article_text

class RelationshipTracerTests(unittest.TestCase):
    def test_extracts_decree_and_circular_with_relation_types(self):
        text = ("Ủy ban nhân dân tỉnh tổ chức triển khai thực hiện Nghị định số "
                "123/2026/NĐ-CP và hướng dẫn thực hiện Thông tư số 04/2026/TT-BTNMT.")
        refs = extract_document_references(text)
        self.assertEqual(len(refs), 2)
        by_number = {row["referenced_doc_number"]: row for row in refs}
        self.assertEqual(by_number["123/2026/NĐ-CP"]["relation_type"], "trien_khai")
        self.assertEqual(by_number["04/2026/TT-BTNMT"]["relation_type"], "huong_dan")

    def test_extracts_decision_and_citation_context(self):
        refs = extract_document_references("Căn cứ Quyết định số 22/QĐ-UBND ngày 01/11/2026.")
        self.assertEqual(refs[0]["referenced_doc_number"], "22/QĐ-UBND")
        self.assertEqual(refs[0]["relation_type"], "can_cu")
        self.assertIn("Căn cứ", refs[0]["evidence_excerpt"])

    def test_article_text_excludes_related_sidebar(self):
        html = """<html><body><main class='main-content'><p>Triển khai Nghị định số 123/2026/NĐ-CP.</p></main>
        <aside class='related-news'><p>Hướng dẫn Thông tư số 99/2026/TT-BTC.</p></aside></body></html>"""
        text = _article_text(html)
        self.assertIn("123/2026/NĐ-CP",text)
        self.assertNotIn("99/2026/TT-BTC",text)

    def test_generic_thuc_hien_is_not_mislabeled_as_trien_khai(self):
        refs = extract_document_references("Kiểm tra công tác thực hiện Quyết định số 22/2026/QĐ-TTg.")
        self.assertEqual(refs[0]["relation_type"],"thuc_hien")

    def test_resolves_exact_reference_to_one_known_document(self):
        relation = {"referenced_doc_type":"Nghị định","referenced_doc_number":"123/2026/NĐ-CP"}
        known = [{"title":"Nghị định 123/2026/NĐ-CP về hướng dẫn","agency":"Chính phủ",
                  "doc_type":"Nghị định","doc_number":"123/2026/NĐ-CP",
                  "link":"https://chinhphu.vn/van-ban/123"}]
        result = resolve_reference_candidates([relation],known)[0]
        self.assertEqual(result["resolution_status"],"found_in_scan_index")
        self.assertEqual(result["matched_documents"][0]["link"],"https://chinhphu.vn/van-ban/123")

    def test_does_not_pick_one_when_same_number_is_ambiguous(self):
        relation = {"referenced_doc_type":"Quyết định","referenced_doc_number":"12/2026/QĐ-UBND"}
        known = [
            {"title":"Quyết định 12/2026/QĐ-UBND","agency":"UBND tỉnh A","doc_type":"Quyết định","doc_number":"12/2026/QĐ-UBND","link":"https://a.gov.vn/12"},
            {"title":"Quyết định 12/2026/QĐ-UBND","agency":"UBND tỉnh B","doc_type":"Quyết định","doc_number":"12/2026/QĐ-UBND","link":"https://b.gov.vn/12"},
        ]
        result = resolve_reference_candidates([relation],known)[0]
        self.assertEqual(result["resolution_status"],"ambiguous_multiple_matches")
        self.assertEqual(len(result["matched_documents"]),2)

    def test_merge_deduplicates_same_edge(self):
        row = {"source_url":"https://example.gov.vn/a","referenced_doc_number":"1/2026/NĐ-CP","relation_type":"trien_khai"}
        self.assertEqual(len(merge_relationships([row],[row])),1)

if __name__ == "__main__":
    unittest.main()
