import unittest
from pathlib import Path


class GitHubControllerContractTests(unittest.TestCase):
    def test_github_schedule_is_the_only_scheduler(self):
        workflow = Path(".github/workflows/auto_scan.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "*/5 * * * *"', workflow)
        scheduler = Path("scripts/github_scheduler.js").read_text(encoding="utf-8")
        self.assertIn("createWorkflowDispatch", scheduler)
        self.assertIn('inputs: { profile: dispatchedProfile }', scheduler)
        self.assertIn('priority_only', workflow)
        self.assertIn('full_only', workflow)

    def test_cooldown_is_measured_from_job_completion(self):
        workflow = Path(".github/workflows/auto_scan.yml").read_text(encoding="utf-8")
        scheduler = Path("scripts/github_scheduler.js").read_text(encoding="utf-8")
        self.assertIn("job.completed_at", scheduler)
        self.assertIn("priorityAge >= 5", scheduler)
        self.assertIn("fullAge >= 30", scheduler)
        self.assertIn("fullAge >= 5", scheduler)
        self.assertIn("globalCooldownAge < 5", scheduler)
        self.assertIn("latestAnyCompleted", scheduler)

    def test_controller_prevents_duplicate_and_recovers_stale_runs(self):
        workflow = Path(".github/workflows/auto_scan.yml").read_text(encoding="utf-8")
        scheduler = Path("scripts/github_scheduler.js").read_text(encoding="utf-8")
        self.assertIn('["queued", "pending", "in_progress"]', scheduler)
        self.assertIn("no duplicate dispatch", scheduler)
        self.assertIn("cancelWorkflowRun", scheduler)

    def test_apps_script_has_no_scheduler_or_github_credentials(self):
        code = Path("apps_script/Code.gs").read_text(encoding="utf-8")
        self.assertNotIn("GITHUB_PAT", code)
        self.assertNotIn("createWorkflowDispatch", code)
        self.assertNotIn("guiLenhQuetGitHub_", code)
        self.assertNotIn("ScriptApp.newTrigger", code)
        self.assertIn("xoaTriggerDieuPhoiCu_", code)
        self.assertIn("function quetNhanhTrungUongTuSheet()", code)
        self.assertIn('version: "15.0"', code)

    def test_python_source_registry_and_memory_are_github_owned(self):
        code = Path("quet_vb.py").read_text(encoding="utf-8")
        self.assertIn("load_sources_from_csv()", code)
        self.assertNotIn("get_sources_and_memory", code)
        self.assertNotIn("fetch_source_via_apps_script", code)
        sheets = Path("scanner/sheets.py").read_text(encoding="utf-8")
        self.assertNotIn("def get_sources_and_memory", sheets)
        self.assertNotIn("def fetch_source_via_apps_script", sheets)

    def test_controller_checks_thirty_recent_runs_for_long_running_jobs(self):
        workflow = Path(".github/workflows/auto_scan.yml").read_text(encoding="utf-8")
        scheduler = Path("scripts/github_scheduler.js").read_text(encoding="utf-8")
        self.assertIn(".slice(0, 30)", scheduler)
        self.assertIn("timeout-minutes: 40", workflow)

    def test_apps_script_is_only_a_result_receiver(self):
        code = Path("apps_script/Code.gs").read_text(encoding="utf-8")
        self.assertIn('data.action === "save_results"', code)
        self.assertNotIn('data.action === "get_sources"', code)
        self.assertNotIn('data.action === "fetch_source"', code)
        self.assertNotIn("function getSources_(", code)
        self.assertNotIn("function fetchSource_(", code)

    def test_apps_script_requires_api_token_and_matches_source_status_by_url(self):
        code = Path("apps_script/Code.gs").read_text(encoding="utf-8")
        self.assertIn("if (!expectedToken)", code)
        self.assertIn('String(data.token || "") !== expectedToken', code)
        self.assertIn("rowByUrl.get(key)", code)
        self.assertIn('st.url || ""', code)

    def test_sheets_write_has_retry_repair_logic(self):
        code = Path("apps_script/Code.gs").read_text(encoding="utf-8")
        self.assertIn("Repair-safe two-table write", code)
        self.assertIn("repaired_memory_only", code)
        self.assertIn("repaired_result_only", code)
        for helper in ("ensureMemorySheet_", "backfillLegacyMemory_", "legacyDocumentIdentity_", "formatBatchRows_"):
            self.assertIn("function " + helper, code)


if __name__ == "__main__":
    unittest.main()
