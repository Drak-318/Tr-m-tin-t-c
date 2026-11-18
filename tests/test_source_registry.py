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

    def test_empty_priority_list_does_not_select_any_source(self):
        selected, missing = filter_priority_sources(
            [{"name": "A", "url": "https://a.gov.vn"}], []
        )
        self.assertEqual(selected, [])
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
