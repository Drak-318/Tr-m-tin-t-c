import unittest

from scanner.source_registry import filter_priority_sources, filter_non_priority_sources, load_sources_from_csv


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

    def test_filter_non_priority_excludes_every_priority_url(self):
        sources = [
            {"name":"Government","url":"https://chinhphu.vn/he-thong-van-ban"},
            {"name":"TVPL","url":"https://thuvienphapluat.vn/list"},
            {"name":"Other","url":"https://other.gov.vn/list"},
        ]
        remaining = filter_non_priority_sources(
            sources, ["https://chinhphu.vn/he-thong-van-ban/", "https://thuvienphapluat.vn/list"]
        )
        self.assertEqual([row["name"] for row in remaining], ["Other"])

    def test_empty_priority_list_does_not_select_any_source(self):
        selected, missing = filter_priority_sources(
            [{"name": "A", "url": "https://a.gov.vn"}], []
        )
        self.assertEqual(selected, [])
        self.assertEqual(missing, [])



    def test_all_user_requested_sources_are_registered(self):
        from scanner.source_registry import load_sources_from_csv

        expected = {
            "https://kiemtra-phapche.hcm.edu.vn/van-ban/vbplus/41014/0/0/0",
            "https://snv.lamdong.gov.vn/van-ban-chi-dao-dieu-hanh",
            "https://qppl.thanhhoa.gov.vn/vbpq_thanhhoa.nsf",
            "https://syt.lamdong.gov.vn/van-ban-quan-ly",
            "https://stc.lamdong.gov.vn/",
            "https://stp.lamdong.gov.vn/van-ban-chi-dao-dieu-hanh",
            "https://songoaivu.lamdong.gov.vn/",
            "https://snnmt.lamdong.gov.vn/he-thong-van-ban",
            "https://sxd.lamdong.gov.vn/van-ban",
            "https://sxd.quangngai.gov.vn/",
            "https://nhandan.vn/",
        }
        registered = {row["url"].rstrip("/") for row in load_sources_from_csv()}
        expected = {url.rstrip("/") for url in expected}
        self.assertTrue(expected.issubset(registered), expected - registered)

    def test_law_and_resolution_discovery_feeds_are_registered(self):
        from scanner.source_registry import load_sources_from_csv

        names = {row["name"] for row in load_sources_from_csv()}
        self.assertIn("Dò tìm Luật mới - Google News RSS", names)
        self.assertIn("Dò tìm Nghị quyết cấp Trung ương - Google News RSS", names)
        self.assertIn("Tìm kiếm văn bản cấp Trung ương - RSS", names)
        self.assertIn("Dò tìm chính sách địa phương có tác động rộng - Google News RSS", names)

        rows = load_sources_from_csv()
        central = next(row for row in rows if row["name"] == "Tìm kiếm văn bản cấp Trung ương - RSS")
        local = next(row for row in rows if row["name"] == "Dò tìm chính sách địa phương có tác động rộng - Google News RSS")
        self.assertEqual(central["group"], "Văn Bản TW")
        self.assertEqual(local["group"], "Địa phương")
        self.assertIn("site%3Aquochoi.vn", central["url"])
        self.assertNotIn("site%3Alamdong.gov.vn", central["url"])
        self.assertIn("site%3Alamdong.gov.vn", local["url"])


    def test_central_rss_config_excludes_provincial_domains(self):
        import json
        from pathlib import Path

        rows = load_sources_from_csv()
        central = next(row for row in rows if row["name"] == "Tìm kiếm văn bản cấp Trung ương - RSS")
        local = next(row for row in rows if row["name"] == "Dò tìm chính sách địa phương có tác động rộng - Google News RSS")
        config = json.loads(Path("source_config.json").read_text(encoding="utf-8"))
        central_domains = set(config["sources"][central["url"]]["allowed_final_domains"])
        local_domains = set(config["sources"][local["url"]]["allowed_final_domains"])
        self.assertIn("chinhphu.vn", central_domains)
        self.assertIn("vbpl.vn", central_domains)
        self.assertNotIn("lamdong.gov.vn", central_domains)
        self.assertEqual(local_domains, {"lamdong.gov.vn"})


if __name__ == "__main__":
    unittest.main()
