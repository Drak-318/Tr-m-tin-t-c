import unittest
from scanner.relationship_tracer import extract_document_references, merge_relationships

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

    def test_merge_deduplicates_same_edge(self):
        row = {"source_url":"https://example.gov.vn/a","referenced_doc_number":"1/2026/NĐ-CP","relation_type":"trien_khai"}
        self.assertEqual(len(merge_relationships([row],[row])),1)

if __name__ == "__main__":
    unittest.main()
