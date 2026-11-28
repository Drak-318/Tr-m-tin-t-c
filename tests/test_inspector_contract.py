import unittest
from pathlib import Path


class GitHubControllerContractTests(unittest.TestCase):
    def test_github_schedule_is_the_only_scheduler(self):
        workflow = Path(".github/workflows/auto_scan.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "*/5 * * * *"', workflow)
        self.assertIn("createWorkflowDispatch", workflow)
        self.assertIn('inputs: { profile: dispatchedProfile }', workflow)
        self.assertIn('priority_only', workflow)
        self.assertIn('full_only', workflow)

    def test_cooldown_is_measured_from_job_completion(self):
        workflow = Path(".github/workflows/auto_scan.yml").read_text(encoding="utf-8")
        self.assertIn("job.completed_at", workflow)
        self.assertIn("priorityAge >= 5", workflow)
        self.assertIn("Math.max(5, fullInterval)", workflow)

    def test_controller_prevents_duplicate_and_recovers_stale_runs(self):
        workflow = Path(".github/workflows/auto_scan.yml").read_text(encoding="utf-8")
        self.assertIn('["queued", "pending", "in_progress"]', workflow)
        self.assertIn("no duplicate dispatch", workflow)
        self.assertIn("cancelWorkflowRun", workflow)

    def test_apps_script_has_no_scheduler_or_github_credentials(self):
        code = Path("apps_script/Code.gs").read_text(encoding="utf-8")
        self.assertNotIn("GITHUB_PAT", code)
        self.assertNotIn("createWorkflowDispatch", code)
        self.assertNotIn("guiLenhQuetGitHub_", code)
        self.assertNotIn("ScriptApp.newTrigger", code)
        self.assertIn("xoaTriggerDieuPhoiCu_", code)
        self.assertIn('version: "15.0"', code)

    def test_apps_script_is_only_a_result_receiver(self):
        code = Path("apps_script/Code.gs").read_text(encoding="utf-8")
        self.assertIn('data.action === "save_results"', code)
        self.assertNotIn('data.action === "get_sources"', code)
        self.assertNotIn('data.action === "fetch_source"', code)
        self.assertNotIn("function getSources_(", code)
        self.assertNotIn("function fetchSource_(", code)

    def test_sheets_write_has_retry_repair_logic(self):
        code = Path("apps_script/Code.gs").read_text(encoding="utf-8")
        self.assertIn("Repair-safe two-table write", code)
        self.assertIn("repaired_memory_only", code)
        self.assertIn("repaired_result_only", code)


if __name__ == "__main__":
    unittest.main()
