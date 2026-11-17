import json
import tempfile
import unittest
from pathlib import Path

from scanner.state_merge import merge_seen_documents, merge_scan_history, merge_state_files

class StateMergeTests(unittest.TestCase):
    def test_seen_documents_union_preserves_distinct_local_authorities(self):
        remote = {"version":1,"documents":{"a":{"doc_number":"12/QĐ-UBND","agency":"UBND tỉnh A","last_seen":"2026-11-01"}},
                  "urls":{"https://a.gov.vn/12":"a"}}
        local = {"version":1,"documents":{"b":{"doc_number":"12/QĐ-UBND","agency":"UBND tỉnh B","last_seen":"2026-11-02"}},
                 "urls":{"https://b.gov.vn/12":"b"}}
        merged = merge_seen_documents(remote,local)
        self.assertEqual(set(merged["documents"]),{"a","b"})
        self.assertIn("https://a.gov.vn/12",merged["urls"])
        self.assertIn("https://b.gov.vn/12",merged["urls"])

    def test_scan_history_merges_without_duplicate_rows(self):
        a = {"finished_at":"2026-11-01T00:00:00Z","collected":10}
        b = {"finished_at":"2026-11-02T00:00:00Z","collected":20}
        self.assertEqual(merge_scan_history([a],[a,b]),[a,b])

    def test_merge_state_files_keeps_remote_and_local_relationships(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"repo"; local=Path(temp)/"local"
            (root/"data").mkdir(parents=True); (local/"data").mkdir(parents=True)
            (root/"data/seen_documents.json").write_text(json.dumps({"version":1,"documents":{"r":{"last_seen":"2026-11-01"}},"urls":{}}))
            (local/"data/seen_documents.json").write_text(json.dumps({"version":1,"documents":{"l":{"last_seen":"2026-11-02"}},"urls":{}}))
            (root/"data/scan_history.json").write_text('[{"finished_at":"2026-11-01"}]')
            (local/"data/scan_history.json").write_text('[{"finished_at":"2026-11-02"}]')
            (root/"data/document_relationships.json").write_text('[{"source_url":"https://a.gov.vn/1","source_doc_number":"1/2026/QĐ-UBND","referenced_doc_number":"1/2026/NĐ-CP","relation_type":"can_cu"}]')
            (local/"data/document_relationships.json").write_text('[{"source_url":"https://b.gov.vn/2","source_doc_number":"2/2026/QĐ-UBND","referenced_doc_number":"2/2026/NĐ-CP","relation_type":"trien_khai"},{"source_url":"https://noise.gov.vn/3","source_doc_number":"","referenced_doc_number":"3/2026/NĐ-CP","relation_type":"trien_khai"}]')
            (local/"data/relationship_scan_state.json").write_text('{"next_candidate":3}')
            result=merge_state_files(local,root)
            self.assertEqual(result["documents"],2)
            self.assertEqual(result["history"],2)
            self.assertEqual(result["relationships"],2)
            self.assertEqual(json.loads((root/"data/relationship_scan_state.json").read_text())["next_candidate"],3)

if __name__ == "__main__": unittest.main()
