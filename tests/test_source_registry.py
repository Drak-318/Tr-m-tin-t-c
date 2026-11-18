import unittest

from scanner.source_registry import filter_priority_sources


class PrioritySourceTests(unittest.TestCase):
    def test_filter_keeps_only_configured_priority_sources(self):
        sources = [
            {"name": "Other", "url": "https://other.gov.vn/list"},
            {"name": "Government", "url": "https://chinhphu.vn/he-thong-van-ban"},
            {"name": "TVPL", "url": "https://thuvienphapluat.vn/phap-luat/phap-luat-vua-ban-hanh"},
        ]
        selected, missing = filter_priority_sources(
            sources,
            [
                "https://chinhphu.vn/he-thong-van-ban/",
                "https://thuvienphapluat.vn/phap-luat/phap-luat-vua-ban-hanh",
                "https://vbpl.vn/",
            ],
        )
        self.assertEqual([row["name"] for row in selected], ["Government", "TVPL"])
        self.assertEqual(missing, ["https://vbpl.vn"])

    def test_all_priority_urls_exist_in_source_registry(self):
        import json
        from pathlib import Path
        from scanner.source_registry import load_sources_from_csv

        priority = json.loads(Path("priority_sources.json").read_text(encoding="utf-8"))
        sources = load_sources_from_csv()
        selected, missing = filter_priority_sources(sources, priority["urls"])
        self.assertEqual(len(selected), len(priority["urls"]))
        self.assertEqual(missing, [])

    def test_empty_priority_list_does_not_select_any_source(self):
        selected, missing = filter_priority_sources(
            [{"name": "A", "url": "https://a.gov.vn"}], []
        )
        self.assertEqual(selected, [])
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
