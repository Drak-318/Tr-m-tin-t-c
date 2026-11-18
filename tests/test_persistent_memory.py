import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scanner import persistent_memory as memory


class PersistentMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = self.root / "seen_documents.json"
        self.history = self.root / "scan_history.json"
        self.review = self.root / "review_queue.json"
        self.export = self.root / "sheets_export_queue.json"
        self.patches = [
            patch.object(memory, "STATE_PATH", self.state),
            patch.object(memory, "HISTORY_PATH", self.history),
            patch.object(memory, "REVIEW_QUEUE_PATH", self.review),
            patch.object(memory, "EXPORT_QUEUE_PATH", self.export),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_state_is_valid_json_after_write(self):
        state = memory.load_state()
        state["documents"]["id-1"] = {"title": "Văn bản thử nghiệm"}
        memory._write_json(memory.STATE_PATH, state)
        loaded = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertIn("id-1", loaded["documents"])

    def test_review_queue_keeps_one_record_per_canonical_url(self):
        count = memory.enqueue_review_documents([
            {"link": "https://example.gov.vn/a?utm_source=x", "title": "Văn bản A"},
            {"link": "https://example.gov.vn/a", "title": "Văn bản A cập nhật"},
        ])
        queue = memory.load_review_queue()
        self.assertEqual(count, 1)
        self.assertEqual(len(queue), 1)
        self.assertEqual(next(iter(queue.values()))["title"], "Văn bản A cập nhật")

    def test_review_verification_status_is_not_reset_by_next_scan(self):
        memory.enqueue_review_documents([{"link":"https://example.gov.vn/a","title":"Văn bản A"}])
        memory.update_review_document("https://example.gov.vn/a",{
            "verification_status":"date_found","status":"verified_included","document_date":"2026-11-10"
        })
        memory.enqueue_review_documents([{"link":"https://example.gov.vn/a","title":"Văn bản A"}])
        row=memory.load_review_queue()["https://example.gov.vn/a"]
        self.assertEqual(row["status"],"verified_included")
        self.assertEqual(row["verification_status"],"date_found")

    def test_verified_date_evidence_is_not_overwritten_by_undated_rescan(self):
        link="https://example.gov.vn/a"
        memory.enqueue_review_documents([{"link":link,"title":"Kết luận số 123-KL/TW","date_basis":"unknown"}])
        memory.update_review_document(link,{
            "verification_status":"date_found","status":"verified_included",
            "verified_date":"2026-11-13","date_basis":"issue_date_detail",
            "date_evidence":"Ngày ban hành: 13/11/2026"
        })
        memory.enqueue_review_documents([{"link":link,"title":"Kết luận số 123-KL/TW","date_basis":"unknown"}])
        row=memory.load_review_queue()[link]
        self.assertEqual(row["status"],"verified_included")
        self.assertEqual(row["verified_date"],"2026-11-13")
        self.assertEqual(row["date_basis"],"issue_date_detail")
        self.assertEqual(row["date_evidence"],"Ngày ban hành: 13/11/2026")

    def test_pending_review_documents_limits_retries(self):
        memory.enqueue_review_documents([
            {"link":"https://example.gov.vn/a","title":"A"},
            {"link":"https://example.gov.vn/b","title":"B"},
        ])
        memory.update_review_document("https://example.gov.vn/b",{
            "status":"manual_review","attempts":3
        })
        self.assertEqual([r["link"] for r in memory.pending_review_documents(limit=10,max_attempts=3)],
                         ["https://example.gov.vn/a"])

    def test_export_queue_survives_until_explicit_clear(self):
        memory.enqueue_sheets_export({"new_docs": [{"link": "https://example.gov.vn/a"}]})
        self.assertEqual(len(memory.load_sheets_export_queue()), 1)
        memory.clear_sheets_export_queue()
        self.assertEqual(memory.load_sheets_export_queue(), [])



    def test_run_seen_index_blocks_same_identity_from_second_source(self):
        index = memory.RunSeenIndex()
        identity = "number:123/2026/TT-BTC|issuer:TT-BTC|locality:"
        index.add(identity, "https://a.gov.vn/doc/123")
        self.assertTrue(index.contains(identity, "https://b.gov.vn/doc/123"))
        self.assertTrue(index.contains("", "https://a.gov.vn/doc/123"))
        self.assertFalse(index.contains("number:456/2026/TT-BTC", "https://c.gov.vn/doc/456"))

    def test_run_seen_index_uses_canonical_urls(self):
        index = memory.RunSeenIndex()
        index.add("id-1", "https://example.gov.vn/doc?utm_source=one")
        self.assertTrue(index.contains("different-id", "https://example.gov.vn/doc?utm_source=two"))

if __name__ == "__main__":
    unittest.main()
