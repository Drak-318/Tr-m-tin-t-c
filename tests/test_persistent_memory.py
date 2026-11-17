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

    def test_export_queue_survives_until_explicit_clear(self):
        memory.enqueue_sheets_export({"new_docs": [{"link": "https://example.gov.vn/a"}]})
        self.assertEqual(len(memory.load_sheets_export_queue()), 1)
        memory.clear_sheets_export_queue()
        self.assertEqual(memory.load_sheets_export_queue(), [])


if __name__ == "__main__":
    unittest.main()
